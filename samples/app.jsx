import React, { useState, useEffect, useRef } from "react";
import ReactDOM from "react-dom/client";
import { Blobatar } from "@blobatar/react";
import "blobatar/motion.css";

function App() {
  const [capsuleMode, setCapsuleMode] = useState("floating"); // 'floating' | 'island'
  const [animateMode, setAnimateMode] = useState("always");   // 'always' | 'hover'
  const [name, setName] = useState("alain00");
  const [shapeTrait, setShapeTrait] = useState(0.65);
  const [audioLevel, setAudioLevel] = useState(0.4);
  const [isMicOn, setIsMicOn] = useState(false);
  const [size, setSize] = useState(28);

  // Real-time cursor gaze tracking
  const [gaze, setGaze] = useState({ x: 0, y: 0, tilt: 0 });
  const capsuleBlobRef = useRef(null);

  const audioContextRef = useRef(null);
  const analyserRef = useRef(null);
  const animationFrameRef = useRef(null);

  // Window mouse movement listener
  useEffect(() => {
    const handleMouseMove = (e) => {
      if (!capsuleBlobRef.current) return;
      const rect = capsuleBlobRef.current.getBoundingClientRect();
      const cx = rect.left + rect.width / 2;
      const cy = rect.top + rect.height / 2;
      const dx = e.clientX - cx;
      const dy = e.clientY - cy;
      const dist = Math.hypot(dx, dy);
      if (dist < 1) return;

      const nx = dx / dist;
      const ny = dy / dist;
      const reachX = nx * Math.min(1.4, dist * 0.005);
      const reachY = ny * Math.min(1.1, dist * 0.005);
      const tiltAngle = nx * Math.min(4.5, dist * 0.008);

      setGaze({ x: reachX, y: reachY, tilt: tiltAngle });
    };

    window.addEventListener("mousemove", handleMouseMove);
    return () => window.removeEventListener("mousemove", handleMouseMove);
  }, []);

  // Live microphone capture
  const toggleMic = async () => {
    if (!isMicOn) {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        const source = audioCtx.createMediaStreamSource(stream);
        const analyser = audioCtx.createAnalyser();
        analyser.fftSize = 256;
        source.connect(analyser);

        audioContextRef.current = audioCtx;
        analyserRef.current = analyser;
        setIsMicOn(true);

        const dataArray = new Uint8Array(analyser.frequencyBinCount);
        const loop = () => {
          analyser.getByteFrequencyData(dataArray);
          let sum = 0;
          for (let i = 0; i < dataArray.length; i++) sum += dataArray[i];
          const avg = sum / dataArray.length;
          const norm = Math.min(1.0, avg / 65);
          setAudioLevel(norm);
          animationFrameRef.current = requestAnimationFrame(loop);
        };
        loop();
      } catch (err) {
        alert("Microphone error: " + err);
      }
    } else {
      if (audioContextRef.current) audioContextRef.current.close();
      if (animationFrameRef.current) cancelAnimationFrame(animationFrameRef.current);
      setIsMicOn(false);
      setAudioLevel(0.3);
    }
  };

  return (
    <div className="container">
      <header className="header">
        <h1 className="title">OpenFlow · MIRA Blobatar React Sample</h1>
        <p className="subtitle">
          Official <code>@blobatar/react</code> capsule with live mouse pointer gaze tracking &amp; head tilt
        </p>
      </header>

      {/* STAGE CONTAINER */}
      <div className="stage-card">
        {capsuleMode === "island" && <div className="screen-notch-bar" />}

        {/* CAPSULE DEMO */}
        <div className="capsule-section">
          <div className={`openflow-capsule ${capsuleMode === "island" ? "island" : "floating"}`}>
            {/* The exact Blobatar component with cursor gaze tracking */}
            <div
              ref={capsuleBlobRef}
              className="blobatar-wrapper"
              style={{
                filter: `drop-shadow(0 0 ${8 + audioLevel * 14}px rgba(165, 221, 255, ${0.45 + audioLevel * 0.45}))`,
                transform: `perspective(500px) rotateY(${gaze.tilt}deg) rotateX(${-gaze.y * 3}deg) translate(${gaze.x * 2}px, ${gaze.y * 2}px) scale(${1.0 + audioLevel * 0.15})`,
                transition: "transform 0.05s ease-out, filter 0.08s ease",
              }}
            >
              <Blobatar
                name={name}
                traits={{ shape: shapeTrait }}
                animate={animateMode}
                size={size}
                style={{
                  "--mo-look-x": String(gaze.x),
                  "--mo-look-y": String(gaze.y),
                }}
              />
            </div>

            <span className="capsule-text">Listening</span>
            <span className="dialect-badge">Sambalpuri</span>

            {/* Audio Wave Bars */}
            <div className="wave-bars">
              {[0, 1, 2, 3].map((i) => (
                <div
                  key={i}
                  className="wave-bar"
                  style={{
                    height: `${Math.max(4, 4 + audioLevel * 14 * Math.sin((i + 1) * 1.5)) }px`,
                  }}
                />
              ))}
            </div>
          </div>
        </div>

        {/* MACRO CLOSE-UP INSPECTION */}
        <div className="macro-section">
          <div className="macro-label">High-Definition Living Preview (Move Mouse Anywhere to See Eye Tracking!)</div>
          <div
            className="macro-avatar-box"
            style={{
              filter: `drop-shadow(0 0 ${20 + audioLevel * 25}px rgba(165, 221, 255, ${0.4 + audioLevel * 0.5}))`,
              transform: `perspective(600px) rotateY(${gaze.tilt * 1.5}deg) rotateX(${-gaze.y * 5}deg) translate(${gaze.x * 6}px, ${gaze.y * 6}px) scale(${1.0 + audioLevel * 0.12})`,
              transition: "transform 0.05s ease-out, filter 0.1s ease",
            }}
          >
            <Blobatar
              name={name}
              traits={{ shape: shapeTrait }}
              animate={animateMode}
              size={120}
              style={{
                "--mo-look-x": String(gaze.x * 1.2),
                "--mo-look-y": String(gaze.y * 1.2),
              }}
            />
          </div>
          <div className="macro-meta">
            <span>Mouse Gaze: <strong>X: {gaze.x.toFixed(2)}, Y: {gaze.y.toFixed(2)}</strong></span> · 
            <span>Head Tilt: <strong>{gaze.tilt.toFixed(1)}°</strong></span> · 
            <span>Shape: <strong>Capsule ({shapeTrait})</strong></span>
          </div>
        </div>

        {/* CODE SNIPPET BOX */}
        <div className="code-box">
          <div className="code-header">Implemented Component Code</div>
          <pre>
{`import { Blobatar } from "@blobatar/react";
import "blobatar/motion.css";

// shape: capsule (with Gaussian blend aura & pointer tracking)
<Blobatar
  name="${name}"
  traits={{ shape: ${shapeTrait} }}
  animate="${animateMode}"
  style={{
    "--mo-look-x": "${gaze.x.toFixed(2)}",
    "--mo-look-y": "${gaze.y.toFixed(2)}"
  }}
/>`}
          </pre>
        </div>

        {/* CONTROLS */}
        <div className="controls-grid">
          <div className="control-item">
            <label>Capsule Style</label>
            <div className="btn-group">
              <button
                className={capsuleMode === "floating" ? "active" : ""}
                onClick={() => setCapsuleMode("floating")}
              >
                Floating Pill
              </button>
              <button
                className={capsuleMode === "island" ? "active" : ""}
                onClick={() => setCapsuleMode("island")}
              >
                Top Dynamic Island
              </button>
            </div>
          </div>

          <div className="control-item">
            <label>Motion Trigger</label>
            <div className="btn-group">
              <button
                className={animateMode === "always" ? "active" : ""}
                onClick={() => setAnimateMode("always")}
              >
                Always Listening
              </button>
              <button
                className={animateMode === "hover" ? "active" : ""}
                onClick={() => setAnimateMode("hover")}
              >
                On Hover
              </button>
            </div>
          </div>

          <div className="control-item">
            <label>Voice Audio Reactivity</label>
            <button
              className={`mic-btn ${isMicOn ? "mic-active" : ""}`}
              onClick={toggleMic}
            >
              {isMicOn ? "🔴 Microphone Active (Speak!)" : "🎙️ Enable Microphone"}
            </button>
            {!isMicOn && (
              <div style={{ marginTop: 8 }}>
                <input
                  type="range"
                  min="0"
                  max="100"
                  value={Math.round(audioLevel * 100)}
                  onChange={(e) => setAudioLevel(e.target.value / 100)}
                />
                <span className="slider-label">Simulated Volume: {Math.round(audioLevel * 100)}%</span>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(<App />);
