package app.openflow

import android.accessibilityservice.AccessibilityService
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import android.graphics.PixelFormat
import android.graphics.Rect
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import android.view.accessibility.AccessibilityWindowInfo
import android.view.animation.OvershootInterpolator
import android.widget.Toast
import java.io.File

/**
 * Watches for a focused, editable text field in any app, shows a small round button, and on tap a compact capsule.
 * While you speak, the recognised words are typed into the field live. Both views can be dragged; the spot is remembered.
 * Overlays use TYPE_ACCESSIBILITY_OVERLAY, which needs no "draw over other apps" permission.
 */
class FlowService : AccessibilityService() {
    private lateinit var wm: WindowManager
    private val ui = Handler(Looper.getMainLooper())
    private var bubble: BubbleView? = null
    private var capsule: CapsuleView? = null
    private var recorder: LevelRecorder? = null
    private var engine: SpeechEngine? = null
    private var engineLoading = false
    @Volatile private var streaming = false
    private var baseText = ""      // the field's text before / after the spot where live words go
    private var afterText = ""
    private var lastShown = ""
    private val d get() = resources.displayMetrics.density
    private val prefs get() = getSharedPreferences("flow", MODE_PRIVATE)
    private val unload = Runnable { engine?.close(); engine = null }   // frees the model after 10 idle minutes

    private fun lang() = prefs.getString("lang", "or") ?: "or"
    private fun modelDir(l: String = lang()) = File(filesDir, "models/$l")
    private fun modelReady(l: String = lang()): Boolean {
        val d = modelDir(l)
        return (File(d, "model.onnx").exists() || File(d, "model.int8.onnx").exists()) &&
            (File(d, "vocab.json").exists() || File(d, "tokens.txt").exists())
    }

    private fun loadEngineAsync(l: String = lang()) {
        if (engine?.lang == l || engineLoading || !modelReady(l)) return
        engine?.close()
        engine = null
        engineLoading = true
        Thread {
            runCatching { SpeechEngine(l, modelDir(l)) }
                .onSuccess { engine = it; Log.d("OpenFlow", "Loaded engine for $l") }
                .onFailure { Log.e("OpenFlow", "model load failed for $l", it) }
            engineLoading = false
        }.start()
    }

    // ---------------------------------------------------------------- lifecycle

    override fun onServiceConnected() {
        wm = getSystemService(WINDOW_SERVICE) as WindowManager
        if (applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE != 0) {   // developer hook: feed a WAV file to the engine
            val f = IntentFilter("app.openflow.TEST_WAV")
            if (Build.VERSION.SDK_INT >= 33) registerReceiver(testReceiver, f, Context.RECEIVER_EXPORTED) else registerReceiver(testReceiver, f)
        }
    }

    override fun onInterrupt() {}
    override fun onUnbind(intent: Intent?): Boolean { stopListening(false); hideBubble(); return super.onUnbind(intent) }

    private val testReceiver = object : BroadcastReceiver() {
        override fun onReceive(c: Context, i: Intent) {
            val b = File(filesDir, i.getStringExtra("wav") ?: return).readBytes()
            val n = (b.size - 44) / 2
            val a = FloatArray(n) { ((b[44 + 2 * it].toInt() and 0xFF) or (b[45 + 2 * it].toInt() shl 8)).toShort() / 32768f }
            loadEngineAsync()
            Thread {
                while (engine == null && engineLoading) Thread.sleep(50)
                val t0 = System.nanoTime()
                val text = engine?.transcribe(a).orEmpty()
                Log.d("OpenFlow", "TEST heard (${(System.nanoTime() - t0) / 1_000_000} ms for ${n / 16000.0} s): $text")
            }.start()
        }
    }

    // ---------------------------------------------------------------- finding the field

    override fun onAccessibilityEvent(e: AccessibilityEvent?) {
        if (capsule != null) return            // listening: leave the screen alone
        ui.removeCallbacks(refresh); ui.postDelayed(refresh, 150)
    }

    private val refresh = Runnable {
        if (capsule != null) return@Runnable
        if (editableFocus() == null) hideBubble() else showBubble()
    }

    private fun editableFocus(): AccessibilityNodeInfo? {
        val root = rootInActiveWindow
        val n = root?.findFocus(AccessibilityNodeInfo.FOCUS_INPUT) ?: root?.let { findEditable(it, 0) }
        return if (n != null && n.isEditable && !n.isPassword && n.packageName != packageName) n else null
    }

    /** Fallback when the app does not report an input focus: the first focused editable node in the tree. */
    private fun findEditable(node: AccessibilityNodeInfo, depth: Int): AccessibilityNodeInfo? {
        if (depth > 25) return null
        if (node.isEditable && (node.isFocused || node.isAccessibilityFocused)) return node
        for (i in 0 until node.childCount) { node.getChild(i)?.let { c -> findEditable(c, depth + 1)?.let { return it } } }
        return null
    }

    // ---------------------------------------------------------------- where the button and capsule sit

    /** Top edge of the keyboard (or null if none is showing). */
    private fun imeTop(): Int? = windows.firstOrNull { it.type == AccessibilityWindowInfo.TYPE_INPUT_METHOD }
        ?.let { val r = Rect(); it.getBoundsInScreen(r); r.top }

    private fun anchorTop() = imeTop() ?: (resources.displayMetrics.heightPixels - (90 * d).toInt())
    private fun offRight() = prefs.getInt("offRight", (8 * d).toInt())
    private fun offUp() = prefs.getInt("offUp", (36 * d).toInt())

    private fun params(w: Int, h: Int): WindowManager.LayoutParams {
        val dm = resources.displayMetrics
        val x = (dm.widthPixels - w - offRight()).coerceIn(0, dm.widthPixels - w)
        val y = (anchorTop() - h - offUp()).coerceIn(0, dm.heightPixels - h)
        return WindowManager.LayoutParams(
            w, h, WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
                WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS or WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
            PixelFormat.TRANSLUCENT
        ).apply { gravity = Gravity.TOP or Gravity.START; this.x = x; this.y = y }
    }

    /** Dragging: the window follows the finger; where it is left is saved relative to the keyboard and the right edge. */
    private val drag = object : Drag {
        override fun move(v: View, dx: Int, dy: Int) {
            val lp = v.layoutParams as WindowManager.LayoutParams
            val dm = resources.displayMetrics
            lp.x = (lp.x + dx).coerceIn(0, dm.widthPixels - lp.width)
            lp.y = (lp.y + dy).coerceIn(0, dm.heightPixels - lp.height)
            wm.updateViewLayout(v, lp)
        }

        override fun end(v: View) {
            val lp = v.layoutParams as WindowManager.LayoutParams
            val dm = resources.displayMetrics
            prefs.edit().putInt("offRight", dm.widthPixels - (lp.x + lp.width)).putInt("offUp", anchorTop() - (lp.y + lp.height)).apply()
        }
    }

    private fun popIn(v: View, pivotX: Float, pivotY: Float, from: Float) {
        v.pivotX = pivotX; v.pivotY = pivotY
        v.alpha = 0f; v.scaleX = from; v.scaleY = from
        v.animate().alpha(1f).scaleX(1f).scaleY(1f).setDuration(240).setInterpolator(OvershootInterpolator(1.3f)).start()
    }

    private fun popOut(v: View, then: () -> Unit = {}) {
        v.animate().alpha(0f).scaleX(0.8f).scaleY(0.8f).setDuration(140).withEndAction { runCatching { wm.removeView(v) }; then() }.start()
    }

    // ---------------------------------------------------------------- the button

    private fun showBubble() {
        val size = (48 * d).toInt()
        val v = bubble
        if (v == null) {
            val b = BubbleView(this, drag) { startListening() }
            bubble = b
            wm.addView(b, params(size, size))
            popIn(b, size / 2f, size / 2f, 0.5f)
        } else if (v.alpha > 0.5f) {
            // keep it where the user put it; just follow the keyboard
            val lp = v.layoutParams as WindowManager.LayoutParams
            val np = params(size, size)
            if (lp.x != np.x || lp.y != np.y) { lp.x = np.x; lp.y = np.y; wm.updateViewLayout(v, lp) }
        }
    }

    private fun hideBubble() { bubble?.let { b -> bubble = null; popOut(b) } }

    // ---------------------------------------------------------------- listening, with live typing

    private fun startListening() {
        if (editableFocus() == null) return
        val b = bubble; bubble = null
        b?.let { runCatching { wm.removeView(it) } }
        val lang = lang()
        val badge = when (lang) { "or" -> "OR"; "hi" -> "HI"; else -> "EN" }
        val c = CapsuleView(this, badge, drag) { stopListening(true) }
        capsule = c
        wm.addView(c, params(c.wPx, c.hPx))
        popIn(c, c.wPx.toFloat(), c.hPx / 2f, 0.6f)
        c.performHapticFeedback(android.view.HapticFeedbackConstants.KEYBOARD_TAP)
        when {
            !modelReady(lang) -> {
                val name = when (lang) { "or" -> "Odia"; "hi" -> "Hindi"; else -> "English" }
                c.setMessage("$name model not installed")
                ui.postDelayed({ stopListening(false) }, 1800); return
            }
            checkSelfPermission(android.Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED ->
                { c.setMessage("Allow the microphone in OpenFlow"); ui.postDelayed({ stopListening(false) }, 2200); return }
        }
        ui.removeCallbacks(unload); loadEngineAsync(lang)
        val r = LevelRecorder { c.setLevel(it) }
        if (!r.start()) { c.setMessage("Microphone is busy"); ui.postDelayed({ stopListening(false) }, 1800); return }
        recorder = r
        beginLive()
        startStream(r)
    }

    /** Remembers the text around the cursor, so each live update can rebuild: before + words so far + after. */
    private fun beginLive() {
        val n = editableFocus()
        val cur = if (n == null || n.isShowingHintText) "" else (n.text?.toString() ?: "")
        val s = n?.textSelectionStart?.let { if (it in 0..cur.length) it else cur.length } ?: cur.length
        val e = n?.textSelectionEnd?.let { if (it in 0..cur.length) it else s } ?: s
        baseText = cur.substring(0, minOf(s, e)); afterText = cur.substring(maxOf(s, e)); lastShown = ""
    }

    private fun showLive(text: String) {
        if (text == lastShown) return
        lastShown = text
        val n = editableFocus() ?: return
        n.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, Bundle().apply {
            putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, baseText + text + afterText) })
        val pos = baseText.length + text.length
        n.performAction(AccessibilityNodeInfo.ACTION_SET_SELECTION, Bundle().apply {
            putInt(AccessibilityNodeInfo.ACTION_ARGUMENT_SELECTION_START_INT, pos)
            putInt(AccessibilityNodeInfo.ACTION_ARGUMENT_SELECTION_END_INT, pos) })
    }

    /**
     * Recognition loop: every half second the speech since the last pause is decoded and shown. A pause (or 12 s of
     * speech) locks that part in, so only a short tail is ever re-decoded and the work stays small.
     */
    private fun startStream(r: LevelRecorder) {
        streaming = true
        Thread {
            var committed = ""
            var tailStart = 0
            while (streaming) {
                Thread.sleep(500)
                val e = engine ?: continue
                val cur = r.length
                if (cur - tailStart < 4800) continue
                val t = if (r.peak(tailStart, cur) < 0.006f) "" else runCatching { e.transcribe(r.samples(tailStart, cur)) }.getOrDefault("")   // no speech: no guessing
                if ((r.quietFor(700) && cur - tailStart > 32000) || cur - tailStart > 16000 * 12) {
                    if (t.isNotEmpty()) committed += "$t "
                    tailStart = cur
                    ui.post { showLive(committed) }
                } else ui.post { showLive(committed + t) }
            }
            // the last, complete pass once the user has stopped
            Thread.sleep(150)
            var waited = 0
            while (engine == null && engineLoading && waited < 100) { Thread.sleep(100); waited++ }
            val cur = r.length
            val last = if (cur - tailStart >= 1600 && r.peak(tailStart, cur) >= 0.006f) runCatching { engine?.transcribe(r.samples(tailStart, cur)) }.getOrNull().orEmpty() else ""
            val rawFinal = (committed + last).trim()
            val finalText = TextFormatter.format(rawFinal, lang(), isFinal = true)
            Log.d("OpenFlow", "heard: $finalText")
            ui.post {
                if (finalText.isNotEmpty()) {
                    showLive("$finalText ")
                    Db.get(this).add(lang(), finalText)   // History tab
                    capsule?.performHapticFeedback(android.view.HapticFeedbackConstants.KEYBOARD_TAP)
                }
                capsule?.let { c -> capsule = null; popOut(c) { ui.postDelayed(refresh, 120) } }
                ui.postDelayed(unload, 10 * 60 * 1000L)
            }
        }.start()
    }

    private fun stopListening(insert: Boolean) {
        val r = recorder
        recorder = null
        r?.stop()
        if (r != null && insert) {
            if (r.totalFrames > 10 && r.silentFrames == r.totalFrames)
                Toast.makeText(this, "Microphone returned silence (blocked by Android?)", Toast.LENGTH_LONG).show()
            capsule?.setMessage("...")
            streaming = false          // the stream thread now does its final pass and closes the capsule
            return
        }
        streaming = false
        capsule?.let { c -> capsule = null; popOut(c) { ui.postDelayed(refresh, 120) } }
    }
}
