package app.openflow

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import org.json.JSONArray
import java.io.File
import java.nio.FloatBuffer
import java.nio.LongBuffer
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.exp
import kotlin.math.ln
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin
import kotlin.math.sqrt

/** Log-mel features exactly as engine/indic_asr.py computes them (pre-emphasis 0.97, 80 Slaney mels, n_fft 512, hop 160). */
object Features {
    const val SR = 16000
    private const val N_FFT = 512
    private const val HOP = 160
    private const val WIN = 400
    private const val MELS = 80
    private const val BINS = N_FFT / 2 + 1

    private fun hzToMel(f: Double) = if (f >= 1000.0) 15.0 + ln(max(f, 1e-10) / 1000.0) / (ln(6.4) / 27.0) else f / (200.0 / 3)
    private fun melToHz(m: Double) = if (m >= 15.0) 1000.0 * exp((ln(6.4) / 27.0) * (m - 15.0)) else m * (200.0 / 3)

    private val filters: Array<FloatArray> = run {
        val lo = hzToMel(0.0); val hi = hzToMel(8000.0)
        val hz = DoubleArray(MELS + 2) { melToHz(lo + (hi - lo) * it / (MELS + 1)) }
        Array(MELS) { m ->
            FloatArray(BINS) { k ->
                val f = SR / 2.0 * k / (BINS - 1)
                val lower = (f - hz[m]) / (hz[m + 1] - hz[m])
                val upper = (hz[m + 2] - f) / (hz[m + 2] - hz[m + 1])
                (max(0.0, min(lower, upper)) * 2.0 / (hz[m + 2] - hz[m])).toFloat()
            }
        }
    }

    private val window = FloatArray(N_FFT).also { w ->
        val off = (N_FFT - WIN) / 2
        for (i in 0 until WIN) w[off + i] = (0.5 - 0.5 * cos(2 * PI * i / WIN)).toFloat()
    }

    private val cosT = DoubleArray(N_FFT / 2) { cos(2 * PI * it / N_FFT) }
    private val sinT = DoubleArray(N_FFT / 2) { -sin(2 * PI * it / N_FFT) }

    /** In-place radix-2 FFT of 512 points. */
    private fun fft(re: DoubleArray, im: DoubleArray) {
        val n = N_FFT
        var j = 0
        for (i in 1 until n) {
            var bit = n shr 1
            while (j and bit != 0) { j = j xor bit; bit = bit shr 1 }
            j = j xor bit
            if (i < j) { val a = re[i]; re[i] = re[j]; re[j] = a; val b = im[i]; im[i] = im[j]; im[j] = b }
        }
        var len = 2
        while (len <= n) {
            val half = len / 2; val step = n / len
            var i = 0
            while (i < n) {
                for (k in 0 until half) {
                    val wr = cosT[k * step]; val wi = sinT[k * step]
                    val a = i + k; val b = a + half
                    val tr = re[b] * wr - im[b] * wi; val ti = re[b] * wi + im[b] * wr
                    re[b] = re[a] - tr; im[b] = im[a] - ti; re[a] += tr; im[a] += ti
                }
                i += len
            }
            len = len shl 1
        }
    }

    /** Returns the [80, T] features row-major, and T. */
    fun compute(audio: FloatArray): Pair<FloatArray, Int> {
        val pad = N_FFT / 2
        val y = FloatArray(audio.size + 2 * pad)
        for (i in audio.indices) y[pad + i] = if (i == 0) audio[0] else audio[i] - 0.97f * audio[i - 1]
        val t = 1 + (y.size - N_FFT) / HOP
        val logmel = Array(MELS) { FloatArray(t) }
        val re = DoubleArray(N_FFT); val im = DoubleArray(N_FFT); val power = FloatArray(BINS)
        for (f in 0 until t) {
            val s = f * HOP
            for (i in 0 until N_FFT) { re[i] = (y[s + i] * window[i]).toDouble(); im[i] = 0.0 }
            fft(re, im)
            for (k in 0 until BINS) power[k] = (re[k] * re[k] + im[k] * im[k]).toFloat()
            for (m in 0 until MELS) {
                var acc = 0f
                val fl = filters[m]
                for (k in 0 until BINS) acc += fl[k] * power[k]
                logmel[m][f] = ln(acc + 5.9604645e-8f)   // 2 ** -24
            }
        }
        val out = FloatArray(MELS * t)
        for (m in 0 until MELS) {
            var mean = 0.0; for (f in 0 until t) mean += logmel[m][f]; mean /= t
            var v = 0.0; for (f in 0 until t) { val d = logmel[m][f] - mean; v += d * d }
            val std = sqrt(v / max(1, t - 1))
            for (f in 0 until t) out[m * t + f] = ((logmel[m][f] - mean) / (std + 1e-5)).toFloat()
        }
        return out to t
    }
}

/**
 * Universal Conformer CTC speech engine (int8 ONNX).
 * Supports both Odia (vocab.json) and English (tokens.txt).
 */
open class SpeechEngine(val lang: String, dir: File) : AutoCloseable {
    private val env = OrtEnvironment.getEnvironment()
    private val session: OrtSession
    private val vocab: List<String>
    private val blank: Int
    private val allowed: BooleanArray?

    init {
        val tokensFile = File(dir, "tokens.txt")
        val vocabFile = File(dir, "vocab.json")
        if (tokensFile.exists()) {
            val lines = tokensFile.readLines()
            val map = HashMap<Int, String>()
            var maxIdx = -1
            for (line in lines) {
                val idxSpace = line.lastIndexOf(' ')
                if (idxSpace != -1) {
                    val sym = line.substring(0, idxSpace)
                    val idx = line.substring(idxSpace + 1).toIntOrNull()
                    if (idx != null) {
                        map[idx] = sym
                        if (idx > maxIdx) maxIdx = idx
                    }
                }
            }
            vocab = List(maxIdx + 1) { map[it] ?: "" }
            blank = maxIdx // last token is <blk>
            allowed = null
        } else {
            val arr = JSONArray(vocabFile.readText())
            vocab = List(arr.length()) { arr.getString(it) }
            blank = vocab.size
            allowed = BooleanArray(vocab.size + 1) { i ->
                i == vocab.size || (vocab[i] != "<unk>" && vocab[i].all { c -> c == '▁' || c.code in 0x0B00..0x0B7F })
            }
        }
        val opts = OrtSession.SessionOptions().apply { setIntraOpNumThreads(4) }
        val modelPath = File(dir, "model.onnx").takeIf { it.exists() }?.absolutePath
            ?: File(dir, "model.int8.onnx").absolutePath
        session = env.createSession(modelPath, opts)
    }

    fun transcribe(audio: FloatArray): String {
        if (audio.size < 1600) return ""
        val (feat, t) = Features.compute(audio)
        OnnxTensor.createTensor(env, FloatBuffer.wrap(feat), longArrayOf(1, 80, t.toLong())).use { x ->
            OnnxTensor.createTensor(env, LongBuffer.wrap(longArrayOf(t.toLong())), longArrayOf(1)).use { len ->
                session.run(mapOf("audio_signal" to x, "length" to len)).use { out ->
                    @Suppress("UNCHECKED_CAST")
                    val logits = (out[0].value as Array<Array<FloatArray>>)[0]
                    val sb = StringBuilder()
                    var prev = -1
                    val allow = allowed
                    for (row in logits) {
                        var best = -1; var bv = Float.NEGATIVE_INFINITY
                        for (i in row.indices) {
                            if ((allow == null || allow[i]) && row[i] > bv) {
                                bv = row[i]; best = i
                            }
                        }
                        if (best != prev && best in 0 until blank) {
                            val tok = vocab[best]
                            if (tok != "<unk>" && tok != "<blk>") {
                                sb.append(tok)
                            }
                        }
                        prev = best
                    }
                    val text = sb.toString()
                        .replace('▁', ' ')
                        .replace('\u2581', ' ')
                        .trim()
                        .replace(Regex("\\s+"), " ")
                    return if (lang == "en") {
                        text.replaceFirstChar { if (it.isLowerCase()) it.titlecase() else it.toString() }
                    } else text
                }
            }
        }
    }

    override fun close() { session.close() }
}

/** Backward compatibility subclass for OdiaEngine */
class OdiaEngine(dir: File) : SpeechEngine("or", dir)
