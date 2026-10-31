package app.openflow

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.RectF
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import kotlin.math.hypot

/** Lets a view be dragged around the screen; the service moves the window and remembers where it was left. */
interface Drag { fun move(v: View, dx: Int, dy: Int); fun end(v: View) }

/** The round button shown beside a focused text field: the OpenFlow mark (an O cut across the middle) on black. */
class BubbleView(context: Context, private val drag: Drag, private val onTap: () -> Unit) : View(context) {
    private val slop = ViewConfiguration.get(context).scaledTouchSlop
    private var downX = 0f; private var downY = 0f; private var lastX = 0f; private var lastY = 0f; private var dragging = false
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
    private var pressed = false

    init {
        contentDescription = "Dictate with OpenFlow"
        isClickable = true
    }

    override fun onDraw(c: Canvas) {
        val w = width.toFloat()
        val d = resources.displayMetrics.density
        val r = 18 * d                      // 36 dp circle inside the 48 dp touch area
        paint.reset(); paint.isAntiAlias = true
        paint.color = 0xFF000000.toInt()
        c.drawCircle(w / 2, w / 2, r, paint)
        paint.style = Paint.Style.STROKE; paint.strokeWidth = d
        paint.color = 0x33FFFFFF
        c.drawCircle(w / 2, w / 2, r - d / 2, paint)
        // the mark, drawn in its 108-unit design space
        val k = (2 * r) / 108f * 0.98f
        c.save()
        c.translate(w / 2 - 54f * k, w / 2 - 54f * k); c.scale(k, k)
        paint.style = Paint.Style.STROKE; paint.strokeWidth = 12f; paint.color = if (pressed) 0xCCFFFFFF.toInt() else 0xFFFFFFFF.toInt()
        c.drawArc(RectF(27.5f, 31.6f, 71.5f, 75.6f), 185.5f, 169f, false, paint)   // top half, shifted left
        c.drawArc(RectF(36.5f, 32.4f, 80.5f, 76.4f), 5.5f, 169f, false, paint)     // bottom half, shifted right
        paint.style = Paint.Style.FILL; paint.color = 0xFF0A84FF.toInt()
        c.drawRoundRect(RectF(43f, 52.4f, 65f, 55.6f), 1.6f, 1.6f, paint)           // the voice
        c.restore()
    }

    override fun onTouchEvent(e: MotionEvent): Boolean {
        when (e.action) {
            MotionEvent.ACTION_DOWN -> { pressed = true; dragging = false; downX = e.rawX; downY = e.rawY; lastX = e.rawX; lastY = e.rawY; invalidate() }
            MotionEvent.ACTION_MOVE -> {
                if (!dragging && hypot(e.rawX - downX, e.rawY - downY) > slop) dragging = true
                if (dragging) {
                    val dx = (e.rawX - lastX).toInt(); val dy = (e.rawY - lastY).toInt()
                    lastX += dx; lastY += dy
                    drag.move(this, dx, dy)
                }
            }
            MotionEvent.ACTION_UP -> { pressed = false; invalidate(); if (dragging) drag.end(this) else onTap() }
            MotionEvent.ACTION_CANCEL -> { pressed = false; invalidate(); if (dragging) drag.end(this) }
        }
        return true
    }
}
