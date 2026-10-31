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
fun HistoryScreen(s: AppState) {
    val ctx = LocalContext.current
    val shown = s.history.filter { s.query.isBlank() || it.text.contains(s.query, ignoreCase = true) }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = androidx.compose.foundation.layout.PaddingValues(bottom = 24.dp)) {
        item { Title("History", "Everything you dictated. Tap one to copy it.") }
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
        item {
            Group(Modifier.padding(horizontal = 16.dp).padding(bottom = 10.dp)) {
                Column(Modifier.padding(16.dp)) {
                    T("Hindi", 17, FontWeight.SemiBold, C.text3)
                    T("Coming soon. It will use the same kind of model as Odia.", 14, c = C.text3, modifier = Modifier.padding(top = 3.dp))
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
                listOf("or" to "Odia", "en" to "English", "hi" to "Hindi (coming soon)").forEachIndexed { i, (code, name) ->
                    if (i > 0) Sep()
                    val on = s.lang == code
                    Row(Modifier.fillMaxWidth().height(56.dp).press { if (code != "hi") s.chooseLang(code) else s.say("Hindi is coming soon") }.padding(horizontal = 16.dp),
                        horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                        T(name, 16, c = if (code == "hi") C.text3 else C.text)
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
