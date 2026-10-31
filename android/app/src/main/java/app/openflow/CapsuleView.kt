package app.openflow

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.RectF
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import kotlin.math.hypot
import kotlin.math.sin

/** The listening capsule: a pulsing red dot, a live waveform, the language, and a stop button. */
class CapsuleView(context: Context, private val lang: String, private val drag: Drag, private val onStop: () -> Unit) : View(context) {
    private val slop = ViewConfiguration.get(context).scaledTouchSlop
    private var downX = 0f; private var downY = 0f; private var lastX = 0f; private var lastY = 0f; private var dragging = false
    private val d = resources.displayMetrics.density
    val wPx = (134 * d).toInt()
    val hPx = (40 * d).toInt()
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val levels = FloatArray(7)
    private val weights = floatArrayOf(.45f, .75f, .95f, 1f, .95f, .75f, .45f)
    private var level = 0f
    private val stopRect = RectF()
    private var message: String? = null

    init { contentDescription = "OpenFlow is listening"; isHapticFeedbackEnabled = true }

    fun setLevel(l: Float) { level = l }
    fun setMessage(m: String?) { message = m }

    override fun onMeasure(w: Int, h: Int) = setMeasuredDimension(wPx, hPx)

    override fun onDraw(c: Canvas) {
        val w = width.toFloat(); val h = height.toFloat()
        paint.reset(); paint.isAntiAlias = true
        paint.color = 0xFF000000.toInt()
        c.drawRoundRect(RectF(0f, 0f, w, h), h / 2, h / 2, paint)
        paint.style = Paint.Style.STROKE; paint.strokeWidth = d; paint.color = 0x33FFFFFF
        c.drawRoundRect(RectF(d / 2, d / 2, w - d / 2, h - d / 2), h / 2, h / 2, paint)
        paint.style = Paint.Style.FILL
        val t = System.nanoTime() / 1e9
        // recording dot
        paint.color = 0xFFFF453A.toInt()
        c.drawCircle(16 * d, h / 2, (3.6f + 0.8f * sin(t * 4).toFloat()) * d, paint)
        val msg = message
        if (msg != null) {
            paint.color = 0xFFFFFFFF.toInt(); paint.textSize = 12 * d
            c.drawText(msg, 28 * d, h / 2 + 4 * d, paint)
        } else {
            for (i in levels.indices) {          // 7 slim bars
                val target = level * weights[i] * (0.85f + 0.15f * sin(t * 6 + i).toFloat())
                levels[i] += (target - levels[i]) * 0.35f
                val bh = (3f + levels[i] * 20f) * d
                val x = 30 * d + i * 6f * d
                paint.color = 0xFFFFFFFF.toInt()
                c.drawRoundRect(RectF(x, h / 2 - bh / 2, x + 2.6f * d, h / 2 + bh / 2), 1.3f * d, 1.3f * d, paint)
            }
            paint.color = 0x99FFFFFF.toInt(); paint.textSize = 11 * d; paint.isFakeBoldText = true
            c.drawText(lang, 30 * d + 7 * 6f * d + 5 * d, h / 2 + 4 * d, paint); paint.isFakeBoldText = false
        }
        // stop button
        val cx = w - 21 * d
        stopRect.set(cx - 22 * d, 0f, w, h)
        paint.color = 0xFFFFFFFF.toInt()
        c.drawCircle(cx, h / 2, 13 * d, paint)
        paint.color = 0xFF000000.toInt()
        c.drawRoundRect(RectF(cx - 4.5f * d, h / 2 - 4.5f * d, cx + 4.5f * d, h / 2 + 4.5f * d), 2f * d, 2f * d, paint)
        postInvalidateOnAnimation()
    }

    override fun onTouchEvent(e: MotionEvent): Boolean {
        when (e.action) {
            MotionEvent.ACTION_DOWN -> { dragging = false; downX = e.rawX; downY = e.rawY; lastX = e.rawX; lastY = e.rawY }
            MotionEvent.ACTION_MOVE -> {
                if (!dragging && hypot(e.rawX - downX, e.rawY - downY) > slop) dragging = true
                if (dragging) {
                    val dx = (e.rawX - lastX).toInt(); val dy = (e.rawY - lastY).toInt()
                    lastX += dx; lastY += dy
                    drag.move(this, dx, dy)
                }
            }
            MotionEvent.ACTION_UP -> {
                if (dragging) drag.end(this)
                else if (stopRect.contains(e.x, e.y)) {
                    performHapticFeedback(android.view.HapticFeedbackConstants.KEYBOARD_TAP)
                    onStop()
                }
            }
            MotionEvent.ACTION_CANCEL -> if (dragging) drag.end(this)
        }
        return true
    }
}
