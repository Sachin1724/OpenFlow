package app.openflow

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import java.io.File
import java.net.HttpURLConnection
import java.net.URL

/** One dictated text, kept on the phone so it can be copied again. */
data class Entry(val id: Long, val ts: Long, val lang: String, val text: String)

/** Dictation history in a tiny SQLite file (no library needed). */
class Db private constructor(ctx: Context) : SQLiteOpenHelper(ctx, "flow.db", null, 1) {
    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE history (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, lang TEXT, text TEXT)")
    }

    override fun onUpgrade(db: SQLiteDatabase, o: Int, n: Int) {}

    fun add(lang: String, text: String) {
        if (text.isBlank()) return
        writableDatabase.insert("history", null, ContentValues().apply {
            put("ts", System.currentTimeMillis()); put("lang", lang); put("text", text.trim()) })
    }

    fun all(limit: Int = 300): List<Entry> = readableDatabase.rawQuery(
        "SELECT id, ts, lang, text FROM history ORDER BY id DESC LIMIT $limit", null).use { c ->
        buildList { while (c.moveToNext()) add(Entry(c.getLong(0), c.getLong(1), c.getString(2), c.getString(3))) }
    }

    fun delete(id: Long) { writableDatabase.delete("history", "id = ?", arrayOf(id.toString())) }
    fun clear() { writableDatabase.delete("history", null, null) }

    companion object {
        @Volatile private var inst: Db? = null
        fun get(ctx: Context): Db = inst ?: synchronized(this) { inst ?: Db(ctx.applicationContext).also { inst = it } }
    }
}

/** A speech model the app can run, and the files it needs. */
data class ModelInfo(val id: String, val title: String, val note: String, val sizeMb: Int, val files: List<Pair<String, String>>)

object Models {
    private const val HF = "https://huggingface.co/"
    private const val EN = "csukuangfj/sherpa-onnx-streaming-zipformer-en-2023-06-26/resolve/main/"
    val all = listOf(
        ModelInfo("or", "Odia", "Speech to Odia script, live. IndicConformer by AI4Bharat.", 188,
            listOf("model.onnx" to HF + "sachinmallick/openflow-odia-asr-int8/resolve/main/or/model.onnx",
                   "vocab.json" to HF + "sachinmallick/openflow-odia-asr-int8/resolve/main/or/vocab.json")),
        ModelInfo("en-live", "English, live", "Types words as you speak. Fast and light.", 69,
            listOf("encoder.int8.onnx" to HF + EN + "encoder-epoch-99-avg-1-chunk-16-left-128.int8.onnx",
                   "decoder.int8.onnx" to HF + EN + "decoder-epoch-99-avg-1-chunk-16-left-128.int8.onnx",
                   "joiner.int8.onnx" to HF + EN + "joiner-epoch-99-avg-1-chunk-16-left-128.int8.onnx",
                   "tokens.txt" to HF + EN + "tokens.txt")),
        ModelInfo("en-whisper", "English, accurate", "Whisper base. Corrects the live text with punctuation.", 57,
            listOf("ggml-base-q5_1.bin" to HF + "ggerganov/whisper.cpp/resolve/main/ggml-base-q5_1.bin")),
    )

    fun dir(ctx: Context, id: String) = File(ctx.filesDir, "models/$id")
    fun installed(ctx: Context, m: ModelInfo) = m.files.all { File(dir(ctx, m.id), it.first).let { f -> f.exists() && f.length() > 0 } }

    /** Downloads every file of a model into its folder, reporting 0..1 progress. Run off the main thread. */
    fun download(ctx: Context, m: ModelInfo, progress: (Float) -> Unit): Result<Unit> = runCatching {
        val dir = dir(ctx, m.id).also { it.mkdirs() }
        val sizes = m.files.map { (_, url) -> head(url) }
        val total = sizes.sum().coerceAtLeast(1L)
        var done = 0L
        for ((i, f) in m.files.withIndex()) {
            val out = File(dir, f.first)
            val tmp = File(dir, f.first + ".part")
            val conn = URL(f.second).openConnection() as HttpURLConnection
            conn.connectTimeout = 15000; conn.readTimeout = 30000
            conn.inputStream.use { ins ->
                tmp.outputStream().use { os ->
                    val buf = ByteArray(64 * 1024)
                    while (true) {
                        val n = ins.read(buf); if (n < 0) break
                        os.write(buf, 0, n); done += n
                        progress((done.toFloat() / total).coerceIn(0f, 1f))
                    }
                }
            }
            if (tmp.length() == 0L) error("empty download: ${f.first}")
            tmp.renameTo(out)
            if (sizes[i] <= 0) done = done  // size unknown: progress is approximate
        }
        progress(1f)
    }.onFailure { dir(ctx, m.id).listFiles()?.filter { it.name.endsWith(".part") }?.forEach { it.delete() } }

    private fun head(url: String): Long = runCatching {
        (URL(url).openConnection() as HttpURLConnection).run { requestMethod = "HEAD"; connectTimeout = 15000; contentLengthLong }
    }.getOrDefault(0L)

    fun delete(ctx: Context, m: ModelInfo) { dir(ctx, m.id).deleteRecursively() }
}
