package app.openflow

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Handler
import android.os.Looper
import java.util.Arrays
import kotlin.math.ln
import kotlin.math.max
import kotlin.math.pow
import kotlin.math.sqrt

/** Reads the microphone (16 kHz mono), keeps up to 90 s of it, and reports loudness 0..1 for the waveform. */
class LevelRecorder(private val onLevel: (Float) -> Unit) {
    private val main = Handler(Looper.getMainLooper())
    @Volatile private var running = false
    @Volatile var silentFrames = 0
        private set
    @Volatile var totalFrames = 0
        private set
    private val pcm = ShortArray(16000 * 90)
    @Volatile private var pcmLen = 0
    private val frameRms = FloatArray(1200)   // loudness of each 50 ms frame, newest overwrites oldest

    val length: Int get() = pcmLen

    /** Samples [from, to) as floats in [-1, 1], with near-field dominant speaker gate applied. */
    fun samples(from: Int = 0, to: Int = pcmLen, gate: Boolean = true): FloatArray {
        val t = minOf(to, pcmLen)
        val raw = FloatArray(max(0, t - from)) { pcm[from + it] / 32768f }
        return if (gate) applyDominantSpeakerGate(raw) else raw
    }

    /** Loudest 50 ms frame between two sample positions: below about 0.006 nobody is speaking. */
    fun peak(from: Int, to: Int): Float {
        var m = 0f
        val last = minOf(to / 800, totalFrames)
        for (f in maxOf(0, from / 800) until last) m = max(m, frameRms[f % frameRms.size])
        return m
    }

    /** True when the last [ms] milliseconds were quiet compared with the room's own noise floor (a pause in speech). */
    fun quietFor(ms: Int): Boolean {
        val n = ms / 50
        val f = totalFrames
        if (f < n + 20) return false
        var recent = 0f
        for (i in 1..n) recent = max(recent, frameRms[(f - i) % frameRms.size])
        var floor = Float.MAX_VALUE
        for (i in 1..minOf(f, 80)) floor = minOf(floor, frameRms[(f - i) % frameRms.size])
        return recent < max(floor * 2.5f, 0.003f)
    }

    @SuppressLint("MissingPermission")
    fun start(): Boolean {
        val min = AudioRecord.getMinBufferSize(16000, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val rec = AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, 16000, AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT, maxOf(min, 4096))
        if (rec.state != AudioRecord.STATE_INITIALIZED) { rec.release(); return false }
        running = true
        rec.startRecording()
        Thread {
            val buf = ShortArray(800) // 50 ms
            while (running) {
                val n = rec.read(buf, 0, buf.size)
                if (n <= 0) continue
                var s = 0.0
                val room = minOf(n, pcm.size - pcmLen)
                if (room > 0) { System.arraycopy(buf, 0, pcm, pcmLen, room); pcmLen += room }
                for (i in 0 until n) { val v = buf[i] / 32768.0; s += v * v }
                val rms = sqrt(s / n).toFloat()
                frameRms[totalFrames % frameRms.size] = rms
                totalFrames++
                if (rms == 0f) silentFrames++   // Android hands a blocked microphone exact zeros
                // log scale: quiet speech from a low-gain microphone still moves the bars
                val level = (ln(1f + rms * 300f) / ln(301f)).coerceIn(0f, 1f)
                main.post { onLevel(level) }
            }
            rec.stop(); rec.release()
        }.start()
        return true
    }

    fun stop() { running = false }

    companion object {
        private const val GATE_DB = 14.0f
        private const val GATE_HOLD_S = 0.35f
        private const val GATE_FRAME = 320     // 20 ms @ 16 kHz
        private const val GATE_INIT_S = 0.60f

        /**
         * Near-field dominant speaker gate:
         * Calibrates dominant energy from the first 0.6 s (90th percentile).
         * Any 20 ms frame more than 14 dB below the dominant floor is zeroed.
         * An adaptive hold timer preserves natural pauses between words.
         */
        fun applyDominantSpeakerGate(
            audio: FloatArray,
            gateDb: Float = GATE_DB,
            holdS: Float = GATE_HOLD_S
        ): FloatArray {
            val sampleRate = 16000
            if (audio.size < (sampleRate * GATE_INIT_S).toInt()) return audio

            val nFrames = audio.size / GATE_FRAME
            if (nFrames < 4) return audio

            val rmsPerFrame = FloatArray(nFrames)
            for (i in 0 until nFrames) {
                val offset = i * GATE_FRAME
                var sumSq = 0.0
                for (j in 0 until GATE_FRAME) {
                    val v = audio[offset + j].toDouble()
                    sumSq += v * v
                }
                rmsPerFrame[i] = sqrt(sumSq / GATE_FRAME).toFloat()
            }

            val calFrames = maxOf(4, (GATE_INIT_S * sampleRate / GATE_FRAME).toInt().coerceAtMost(nFrames))
            val sortedCal = rmsPerFrame.copyOfRange(0, calFrames).apply { sort() }
            val dominantIdx = (calFrames * 0.90f).toInt().coerceIn(0, calFrames - 1)
            val dominantRms = sortedCal[dominantIdx]

            if (dominantRms < 1e-5f) return audio // quiet room or dead mic

            val gateFloor = (dominantRms * 10.0.pow((-gateDb / 20.0).toDouble())).toFloat()
            val holdFrames = maxOf(1, (holdS * sampleRate / GATE_FRAME).toInt())
            val out = audio.copyOf()
            var holdCountdown = 0

            for (i in 0 until nFrames) {
                if (rmsPerFrame[i] >= gateFloor) {
                    holdCountdown = holdFrames
                } else if (holdCountdown > 0) {
                    holdCountdown--
                } else {
                    val offset = i * GATE_FRAME
                    Arrays.fill(out, offset, offset + GATE_FRAME, 0.0f)
                }
            }
            return out
        }
    }
}
