"use client";

import { useEffect, useRef } from "react";

function allowed() {
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return false;
  if (window.matchMedia("(max-width: 47.99rem)").matches) return false;
  const nav = navigator as Navigator & {
    deviceMemory?: number;
    connection?: { saveData?: boolean };
  };
  if (nav.connection?.saveData) return false;
  if ((nav.deviceMemory ?? 8) <= 2) return false;
  if ((navigator.hardwareConcurrency ?? 8) <= 2) return false;
  return true;
}

const VERT = `
attribute vec2 a;
void main() { gl_Position = vec4(a, 0.0, 1.0); }
`;

const FRAG = `
precision mediump float;
uniform vec2 u_res;
uniform float u_time;
uniform vec2 u_pointer;
void main() {
  vec2 uv = gl_FragCoord.xy / u_res;
  vec2 p = uv - 0.5;
  p.x *= u_res.x / max(u_res.y, 1.0);
  vec2 pull = (u_pointer - 0.5) * 0.08;
  float d = length(p - pull);
  float wave = sin((p.x + pull.x) * 7.0 + u_time * 0.18) * cos((p.y + pull.y) * 5.0 - u_time * 0.14);
  float glow = smoothstep(0.85, 0.05, d + wave * 0.05);
  float grid = smoothstep(0.02, 0.0, abs(fract(p.x * 10.0) - 0.5) - 0.47);
  grid += smoothstep(0.02, 0.0, abs(fract(p.y * 8.0) - 0.5) - 0.47);
  vec3 base = vec3(0.035, 0.036, 0.043);
  vec3 accent = vec3(0.84, 1.0, 0.29);
  vec3 col = base + accent * glow * 0.22 + vec3(grid) * 0.035;
  gl_FragColor = vec4(col, 1.0);
}
`;

export function HeroCanvas() {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    if (!allowed()) return;
    const canvas = ref.current;
    if (!canvas) return;
    const gl = canvas.getContext("webgl", { antialias: false, alpha: true, powerPreference: "low-power" });
    if (!gl) return;

    const program = createProgram(gl, VERT, FRAG);
    if (!program) return;
    const buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(program, "a");
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    const uRes = gl.getUniformLocation(program, "u_res");
    const uTime = gl.getUniformLocation(program, "u_time");
    const uPointer = gl.getUniformLocation(program, "u_pointer");
    const pointer = { x: 0.7, y: 0.35 };
    let frame = 0;
    let running = true;
    const started = performance.now();

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
      canvas.width = Math.max(1, Math.floor(rect.width * dpr));
      canvas.height = Math.max(1, Math.floor(rect.height * dpr));
    };
    resize();

    const draw = (now: number) => {
      if (!running) return;
      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.useProgram(program);
      gl.uniform2f(uRes, canvas.width, canvas.height);
      gl.uniform1f(uTime, (now - started) / 1000);
      gl.uniform2f(uPointer, pointer.x, pointer.y);
      gl.drawArrays(gl.TRIANGLES, 0, 6);
      frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);

    const onMove = (event: PointerEvent) => {
      const rect = canvas.getBoundingClientRect();
      pointer.x = (event.clientX - rect.left) / rect.width;
      pointer.y = 1 - (event.clientY - rect.top) / rect.height;
    };
    const observer = new IntersectionObserver(([entry]) => {
      running = entry.isIntersecting;
      if (running) frame = requestAnimationFrame(draw);
      else cancelAnimationFrame(frame);
    });
    observer.observe(canvas);
    window.addEventListener("resize", resize);
    canvas.addEventListener("pointermove", onMove);

    return () => {
      running = false;
      cancelAnimationFrame(frame);
      observer.disconnect();
      window.removeEventListener("resize", resize);
      canvas.removeEventListener("pointermove", onMove);
      gl.deleteProgram(program);
      gl.deleteBuffer(buffer);
    };
  }, []);

  return <canvas ref={ref} className="absolute inset-0 h-full w-full" aria-hidden="true" />;
}

function createProgram(gl: WebGLRenderingContext, vert: string, frag: string) {
  const vs = compile(gl, gl.VERTEX_SHADER, vert);
  const fs = compile(gl, gl.FRAGMENT_SHADER, frag);
  if (!vs || !fs) return null;
  const program = gl.createProgram();
  if (!program) return null;
  gl.attachShader(program, vs);
  gl.attachShader(program, fs);
  gl.linkProgram(program);
  gl.deleteShader(vs);
  gl.deleteShader(fs);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return null;
  return program;
}

function compile(gl: WebGLRenderingContext, type: number, source: string) {
  const shader = gl.createShader(type);
  if (!shader) return null;
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    gl.deleteShader(shader);
    return null;
  }
  return shader;
}
