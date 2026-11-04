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

  // Mouse cursor gaze tracking
  const [gazeX, setGazeX] = useState(0);
  const [gazeY, setGazeY] = useState(0);
  const [tilt, setTilt] = useState(0);

  const audioContextRef = useRef(null);
  const analyserRef = useRef(null);
  const animationFrameRef = useRef(null);

  // Track mouse cursor on screen
  useEffect(() => {
    const handleMouseMove = (e) => {
      const cx = window.innerWidth / 2;
      const cy = window.innerHeight * 0.28;
      const dx = e.clientX - cx;
      const dy = e.clientY - cy;
      const dist = Math.hypot(dx, dy) || 1;
      const factor = Math.min(1.0, dist / 450);
      const gx = (dx / dist) * 1.6 * factor;
      const gy = (dy / dist) * 1.2 * factor;
      const t = (dx / dist) * 5.0 * factor;
      setGazeX(gx);
      setGazeY(gy);
      setTilt(t);
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
          Real-time mouse pointer gaze &amp; 3D head tracking with Gaussian blend ("gaslan")
        </p>
      </header>

      {/* STAGE CONTAINER */}
      <div className="stage-card">
        {capsuleMode === "island" && <div className="screen-notch-bar" />}

        {/* CAPSULE DEMO */}
        <div className="capsule-section">
          <div className={`openflow-capsule ${capsuleMode === "island" ? "island" : "floating"}`}>
            {/* The exact Blobatar component */}
            <div
              className="blobatar-wrapper"
              style={{
                filter: `drop-shadow(0 0 ${8 + audioLevel * 14}px rgba(165, 221, 255, ${0.45 + audioLevel * 0.45}))`,
                transform: `scale(${1.0 + audioLevel * 0.15}) rotate(${tilt * 0.6}deg) translate(${gazeX * 1.5}px, ${gazeY * 1.5}px)`,
                "--mo-look-x": String(gazeX),
                "--mo-look-y": String(gazeY),
                transition: "transform 0.08s ease, filter 0.08s ease",
              }}
            >
              <Blobatar
                name={name}
                traits={{ shape: shapeTrait }}
                animate={animateMode}
                size={size}
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
                    height: `${Math.max(4, 4 + audioLevel * 14 * Math.sin((i + 1) * 1.5))}px`,
                  }}
                />
              ))}
            </div>
          </div>
        </div>

        {/* MACRO CLOSE-UP INSPECTION */}
        <div className="macro-section">
          <div className="macro-label">High-Definition Living Preview (Move Mouse &amp; Watch Him Follow Your Cursor!)</div>
          <div
            className="macro-avatar-box"
            style={{
              filter: `drop-shadow(0 0 ${20 + audioLevel * 25}px rgba(165, 221, 255, ${0.4 + audioLevel * 0.5}))`,
              transform: `scale(${1.0 + audioLevel * 0.12}) rotate(${tilt}deg) translate(${gazeX * 4}px, ${gazeY * 4}px)`,
              "--mo-look-x": String(gazeX * 1.4),
              "--mo-look-y": String(gazeY * 1.4),
              transition: "transform 0.08s ease, filter 0.08s ease",
            }}
          >
            <Blobatar
              name={name}
              traits={{ shape: shapeTrait }}
              animate={animateMode}
              size={120}
            />
          </div>
          <div className="macro-meta">
            <span>Name: <strong>"{name}"</strong></span> · 
            <span>Shape Trait: <strong>{shapeTrait} (Capsule)</strong></span> · 
            <span>Cursor Gaze: <strong>X: {gazeX.toFixed(2)}, Y: {gazeY.toFixed(2)}</strong></span>
          </div>
        </div>

        {/* CODE SNIPPET BOX */}
        <div className="code-box">
          <div className="code-header">Implemented Component Code</div>
          <pre>
{`import { Blobatar } from "@blobatar/react";
import "blobatar/motion.css";

// shape: capsule (with cursor gaze tracking & Gaussian blend aura)
<Blobatar
  name="${name}"
  traits={{ shape: ${shapeTrait} }}
  animate="${animateMode}"
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
