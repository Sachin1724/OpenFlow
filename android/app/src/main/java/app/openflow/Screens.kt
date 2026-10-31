package app.openflow

import android.Manifest
import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.provider.Settings
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.Crossfade
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.systemBars
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.text.DateFormat
import java.util.Date

/** Everything the screens show. Compose reads these values and redraws when they change. */
class AppState(val ctx: Context) {
    private val ui = Handler(Looper.getMainLooper())
    var tab by mutableStateOf(0)
    var toast by mutableStateOf<String?>(null)
    var query by mutableStateOf("")
    val history = mutableStateListOf<Entry>()
    var serviceOn by mutableStateOf(false)
    var micOk by mutableStateOf(false)
    var batteryOk by mutableStateOf(true)
    var lang by mutableStateOf("or")
    var rev by mutableStateOf(0)
    val progress = mutableStateMapOf<String, Float>()
    private val prefs get() = ctx.getSharedPreferences("flow", Context.MODE_PRIVATE)

    fun refresh() {
        serviceOn = (Settings.Secure.getString(ctx.contentResolver, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES) ?: "")
            .contains(FlowService::class.java.name)
        micOk = ctx.checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED
        val pm = ctx.getSystemService(Context.POWER_SERVICE) as? PowerManager
        batteryOk = pm?.isIgnoringBatteryOptimizations(ctx.packageName) ?: true
        lang = prefs.getString("lang", "or") ?: "or"
        history.clear(); history.addAll(Db.get(ctx).all())
        rev++
    }

    fun chooseLang(l: String) { prefs.edit().putString("lang", l).apply(); lang = l }
    fun resetPosition() { prefs.edit().remove("offRight").remove("offUp").apply(); say("Button is back at the right edge") }
    fun say(msg: String) { toast = msg; ui.postDelayed({ if (toast == msg) toast = null }, 1800) }
    fun copy(text: String) {
        (ctx.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager).setPrimaryClip(ClipData.newPlainText("OpenFlow", text))
        say("Copied")
    }

    var sandboxText by mutableStateOf("")
    var isRecordingSandbox by mutableStateOf(false)
    var sandboxLevel by mutableStateOf(0f)
    var sandboxStatus by mutableStateOf<String?>(null)

    private var sandboxRecorder: LevelRecorder? = null
    private var sandboxEngine: SpeechEngine? = null
    @Volatile private var sandboxStreaming = false

    fun toggleSandbox(activity: Activity) {
        if (isRecordingSandbox) {
            stopSandbox()
        } else {
            startSandbox(activity)
        }
    }

    fun clearSandbox() {
        sandboxText = ""
        sandboxStatus = null
    }

    private fun startSandbox(activity: Activity) {
        if (!micOk) {
            activity.requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), 1)
            say("Microphone permission needed")
            return
        }
        val model = Models.all.firstOrNull { it.id == lang }
        if (model == null || !Models.installed(ctx, model)) {
            say("${langName(lang)} model not installed. Visit Models tab.")
            return
        }
        val dir = Models.dir(ctx, lang)
        isRecordingSandbox = true
        sandboxStatus = "Listening..."
        sandboxText = ""

        val r = LevelRecorder { lvl ->
            ui.post { sandboxLevel = lvl }
        }
        if (!r.start()) {
            isRecordingSandbox = false
            sandboxStatus = null
            say("Microphone is busy")
            return
        }
        sandboxRecorder = r
        sandboxStreaming = true

        Thread {
            runCatching {
                if (sandboxEngine == null || sandboxEngine?.lang != lang) {
                    sandboxEngine?.close()
                    sandboxEngine = SpeechEngine(lang, dir)
                }
            }.onFailure {
                ui.post {
                    isRecordingSandbox = false
                    sandboxStatus = null
                    say("Failed to load speech engine")
                }
                return@Thread
            }

            var committed = ""
            var tailStart = 0
            while (sandboxStreaming) {
                Thread.sleep(500)
                val e = sandboxEngine ?: continue
                val cur = r.length
                if (cur - tailStart < 4800) continue
                val t = if (r.peak(tailStart, cur) < 0.006f) "" else runCatching { e.transcribe(r.samples(tailStart, cur)) }.getOrDefault("")
                if ((r.quietFor(700) && cur - tailStart > 32000) || cur - tailStart > 16000 * 12) {
                    if (t.isNotEmpty()) committed += "$t "
                    tailStart = cur
                    val formatted = TextFormatter.format(committed, lang, isFinal = false)
                    ui.post { sandboxText = formatted }
                } else {
                    val formatted = TextFormatter.format(committed + t, lang, isFinal = false)
                    ui.post { sandboxText = formatted }
                }
            }

            // Final pass
            Thread.sleep(150)
            val cur = r.length
            val e = sandboxEngine
            val last = if (e != null && cur - tailStart >= 1600 && r.peak(tailStart, cur) >= 0.006f) {
                runCatching { e.transcribe(r.samples(tailStart, cur), isFinal = true) }.getOrDefault("")
            } else ""
            val rawFinal = (committed + last).trim()
            val formattedFinal = TextFormatter.format(rawFinal, lang, isFinal = true)
            ui.post {
                isRecordingSandbox = false
                sandboxStatus = null
                sandboxLevel = 0f
                if (formattedFinal.isNotEmpty()) {
                    sandboxText = formattedFinal
                    Db.get(ctx).add(lang, formattedFinal)
                    refresh()
                    say("Dictation saved to History")
                }
            }
        }.start()
    }

    private fun stopSandbox() {
        sandboxStreaming = false
        sandboxRecorder?.stop()
        sandboxRecorder = null
        sandboxStatus = "Processing..."
    }
}

@Composable
fun App(s: AppState) {
    Box(Modifier.fillMaxSize().background(C.bg).windowInsetsPadding(WindowInsets.systemBars)) {
        Column(Modifier.fillMaxSize()) {
            Box(Modifier.weight(1f)) {
                Crossfade(s.tab, label = "tab") { t ->
                    when (t) { 0 -> HistoryScreen(s); 1 -> NotesScreen(); 2 -> ModelsScreen(s); else -> SettingsScreen(s) }
                }
            }
            TabBar(s.tab) { s.tab = it }
        }
        AnimatedVisibility(s.toast != null, Modifier.align(Alignment.BottomCenter).padding(bottom = 84.dp),
            enter = fadeIn() + slideInVertically { it / 2 }, exit = fadeOut() + slideOutVertically { it / 2 }) {
            Box(Modifier.clip(RoundedCornerShape(50)).background(C.surface2).padding(horizontal = 20.dp, vertical = 12.dp)) { T(s.toast ?: "", 15, FontWeight.Medium) }
        }
    }
}

private fun ago(ts: Long): String {
    val m = (System.currentTimeMillis() - ts) / 60000
    return when { m < 1 -> "just now"; m < 60 -> "$m min ago"; m < 1440 -> "${m / 60} h ago"
        else -> DateFormat.getDateInstance(DateFormat.MEDIUM).format(Date(ts)) }
}

private fun langName(l: String) = when (l) { "or" -> "Odia"; "en" -> "English"; "hi" -> "Hindi"; else -> l }

// ------------------------------------------------------------------ History

@Composable
fun DictationPlayground(s: AppState) {
    val ctx = LocalContext.current
    val activity = ctx as? Activity
    Group(Modifier.padding(horizontal = 16.dp).padding(bottom = 14.dp)) {
        Column(Modifier.padding(18.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                T("DICTATION PLAYGROUND", 12, FontWeight.Bold, c = C.accent, font = AkiraExpanded)
                Box(Modifier.clip(RoundedCornerShape(6.dp)).background(C.surface2).padding(horizontal = 8.dp, vertical = 4.dp)) {
                    T(langName(s.lang).uppercase(), 11, FontWeight.Bold, c = C.text2)
                }
            }

            Box(Modifier.fillMaxWidth().padding(vertical = 12.dp).clip(RoundedCornerShape(12.dp)).background(C.bg).padding(14.dp)) {
                if (s.sandboxText.isEmpty() && !s.isRecordingSandbox) {
                    T("Tap the microphone and speak to test offline dictation in real time.", 15, c = C.text3, line = 22)
                } else {
                    T(if (s.sandboxText.isEmpty()) "Listening..." else s.sandboxText, 16, c = if (s.sandboxText.isEmpty()) C.text2 else C.text, line = 24)
                }
            }

            if (s.isRecordingSandbox) {
                Row(Modifier.fillMaxWidth().padding(bottom = 12.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    for (i in 0 until 14) {
                        val barHeight = (4.dp + (s.sandboxLevel * 22f * ((i % 4 + 1) / 3f)).dp).coerceIn(4.dp, 26.dp)
                        Box(Modifier.weight(1f).height(barHeight).clip(RoundedCornerShape(2.dp)).background(if (i < 10) C.accent else C.red))
                    }
                }
            }

            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    if (s.sandboxText.isNotEmpty() && !s.isRecordingSandbox) {
                        PillButton("Copy", primary = false, small = true) { s.copy(s.sandboxText) }
                        PillButton("Clear", primary = false, small = true) { s.clearSandbox() }
                    }
                }
                PillButton(
                    if (s.isRecordingSandbox) "Stop" else "Start Dictation",
                    primary = !s.isRecordingSandbox,
                    small = true
                ) {
                    activity?.let { s.toggleSandbox(it) }
                }
            }
        }
    }
}

@Composable
fun HistoryScreen(s: AppState) {
    val ctx = LocalContext.current
    val shown = s.history.filter { s.query.isBlank() || it.text.contains(s.query, ignoreCase = true) }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = androidx.compose.foundation.layout.PaddingValues(bottom = 24.dp)) {
        item { Title("History", "Everything you dictated. Tap one to copy it.") }
        item { DictationPlayground(s) }
        if (!s.serviceOn) item {
            Group(Modifier.padding(horizontal = 16.dp).padding(bottom = 12.dp)) {
                Column(Modifier.padding(16.dp)) {
                    T("Turn on the OpenFlow button", 17, FontWeight.SemiBold)
                    T("It shows a small button next to any text box. Android asks you to allow it once.", 14, c = C.text2, modifier = Modifier.padding(top = 4.dp, bottom = 12.dp))
                    PillButton("Open accessibility settings", small = true) { ctx.startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)) }
                }
            }
        }
        item {
            Box(Modifier.padding(horizontal = 16.dp).padding(bottom = 12.dp).fillMaxWidth().height(44.dp).clip(RoundedCornerShape(50)).background(C.surface)
                .padding(horizontal = 18.dp), contentAlignment = Alignment.CenterStart) {
                BasicTextField(s.query, { s.query = it }, singleLine = true, cursorBrush = SolidColor(C.accent),
                    textStyle = TextStyle(color = C.text, fontSize = 16.sp, fontFamily = Inter), modifier = Modifier.fillMaxWidth(),
                    decorationBox = { inner -> if (s.query.isEmpty()) T("Search", 16, c = C.text3); inner() })
            }
        }
        if (shown.isEmpty()) item {
            T(if (s.history.isEmpty()) "Nothing yet. Tap into a text box in any app, tap the OpenFlow button and speak."
              else "No match.", 15, c = C.text2, modifier = Modifier.padding(horizontal = 24.dp, vertical = 32.dp), line = 22)
        }
        items(shown, key = { it.id }) { e ->
            Group(Modifier.padding(horizontal = 16.dp).padding(bottom = 10.dp).press { s.copy(e.text) }) {
                Column(Modifier.padding(16.dp)) {
                    T(e.text, 16, max = 4, line = 23)
                    Row(Modifier.fillMaxWidth().padding(top = 10.dp), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                        T("${langName(e.lang)}  ·  ${ago(e.ts)}", 13, c = C.text3)
                        Box(Modifier.heightIn48().press { Db.get(ctx).delete(e.id); s.refresh() }, contentAlignment = Alignment.CenterEnd) { T("Delete", 14, FontWeight.Medium, C.red) }
                    }
                }
            }
        }
    }
}

private fun Modifier.heightIn48() = this.then(Modifier.height(36.dp))

// ------------------------------------------------------------------ Notes (meetings, lectures)

@Composable
fun NotesScreen() = Column(Modifier.fillMaxSize()) {
    Title("Notes", "Record a call or a lecture and get notes.")
    Group(Modifier.padding(horizontal = 16.dp)) {
        Column(Modifier.padding(20.dp)) {
            T("Coming next", 17, FontWeight.SemiBold)
            T("This will record with the microphone, write the transcript as you go, and keep each sentence on its own line, like the Windows app.", 15, c = C.text2, modifier = Modifier.padding(top = 6.dp), line = 22)
        }
    }
}

// ------------------------------------------------------------------ Models

@Composable
fun ModelsScreen(s: AppState) {
    val ctx = LocalContext.current
    LazyColumn(Modifier.fillMaxSize(), contentPadding = androidx.compose.foundation.layout.PaddingValues(bottom = 24.dp)) {
        item { Title("Models", "Speech models live on this phone. Download once, then it works offline.") }
        items(Models.all, key = { it.id }) { m ->
            val installed = remember(s.rev) { Models.installed(ctx, m) }
            val p = s.progress[m.id]
            Group(Modifier.padding(horizontal = 16.dp).padding(bottom = 10.dp)) {
                Column(Modifier.padding(16.dp)) {
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f).padding(end = 12.dp)) {
                            T(m.title, 17, FontWeight.SemiBold)
                            T(m.note, 14, c = C.text2, modifier = Modifier.padding(top = 3.dp), line = 20)
                            T("${m.sizeMb} MB", 13, c = C.text3, modifier = Modifier.padding(top = 6.dp))
                        }
                        when {
                            p != null -> T("${(p * 100).toInt()}%", 15, FontWeight.Medium, C.accent)
                            installed -> PillButton("Delete", primary = false, small = true) { Models.delete(ctx, m); s.refresh(); s.say("${m.title} removed") }
                            else -> PillButton("Download", small = true) {
                                s.progress[m.id] = 0f
                                Thread {
                                    Models.download(ctx, m) { s.progress[m.id] = it }
                                        .onSuccess { Handler(Looper.getMainLooper()).post { s.progress.remove(m.id); s.refresh(); s.say("${m.title} is ready") } }
                                        .onFailure { Handler(Looper.getMainLooper()).post { s.progress.remove(m.id); s.say("Download failed. Check your connection.") } }
                                }.start()
                            }
                        }
                    }
                    if (p != null) Box(Modifier.padding(top = 12.dp).fillMaxWidth().height(4.dp).clip(RoundedCornerShape(50)).background(C.surface2)) {
                        Box(Modifier.fillMaxWidth(p.coerceIn(0.02f, 1f)).height(4.dp).clip(RoundedCornerShape(50)).background(C.accent))
                    }
                }
            }
        }

    }
}

// ------------------------------------------------------------------ Settings

@Composable
private fun SettingRow(title: String, value: String, ok: Boolean? = null, action: (@Composable () -> Unit)? = null) =
    Row(Modifier.fillMaxWidth().heightIn48x().padding(horizontal = 16.dp, vertical = 10.dp), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            T(title, 16)
            T(value, 13, c = if (ok == true) C.green else C.text3)
        }
        action?.invoke()
    }

private fun Modifier.heightIn48x() = this.then(Modifier.height(64.dp))

@Composable
fun SettingsScreen(s: AppState) {
    val ctx = LocalContext.current
    LazyColumn(Modifier.fillMaxSize(), contentPadding = androidx.compose.foundation.layout.PaddingValues(bottom = 24.dp)) {
        item { Title("Settings", "") }
        item { SectionLabel("Set up") }
        item {
            Group(Modifier.padding(horizontal = 16.dp)) {
                SettingRow("OpenFlow button", if (s.serviceOn) "On" else "Off", s.serviceOn) {
                    if (!s.serviceOn) PillButton("Turn on", small = true) { ctx.startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)) }
                }
                Sep()
                SettingRow("Microphone", if (s.micOk) "Allowed" else "Not allowed yet", s.micOk) {
                    if (!s.micOk) PillButton("Allow", small = true) { (ctx as Activity).requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), 1) }
                }
                Sep()
                SettingRow("Background battery", if (s.batteryOk) "Unrestricted" else "Optimized (may sleep)", s.batteryOk) {
                    if (!s.batteryOk) PillButton("Keep alive", small = true) {
                        runCatching {
                            val intent = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS).apply {
                                data = Uri.parse("package:${ctx.packageName}")
                            }
                            ctx.startActivity(intent)
                        }.onFailure {
                            ctx.startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
                        }
                    }
                }
            }
        }
        item { SectionLabel("Speak in") }
        item {
            Group(Modifier.padding(horizontal = 16.dp)) {
                listOf("or" to "Odia", "en" to "English", "hi" to "Hindi").forEachIndexed { i, (code, name) ->
                    if (i > 0) Sep()
                    val on = s.lang == code
                    Row(Modifier.fillMaxWidth().height(56.dp).press { s.chooseLang(code) }.padding(horizontal = 16.dp),
                        horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                        T(name, 16)
                        if (on) T("Selected", 14, FontWeight.Medium, C.accent)
                    }
                }
            }
        }
        item { SectionLabel("Button") }
        item {
            Group(Modifier.padding(horizontal = 16.dp)) {
                SettingRow("Position", "Drag the button anywhere; it remembers.") { PillButton("Reset", primary = false, small = true) { s.resetPosition() } }
            }
        }
        item { SectionLabel("History") }
        item {
            Group(Modifier.padding(horizontal = 16.dp)) {
                SettingRow("Clear history", "${s.history.size} saved dictations") {
                    PillButton("Clear", primary = false, small = true) { Db.get(ctx).clear(); s.refresh(); s.say("History cleared") }
                }
            }
        }
        item { SectionLabel("Privacy") }
        item {
            Group(Modifier.padding(horizontal = 16.dp)) {
                T("Speech is recognised on this phone. The only time OpenFlow uses the internet is when you tap Download on a model. " +
                    "The accessibility permission is used to notice a focused text box and to type your words; nothing on your screen is stored or sent.",
                    14, c = C.text2, modifier = Modifier.padding(16.dp), line = 21)
            }
        }
    }
}
