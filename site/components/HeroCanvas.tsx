"use client";

import { Canvas, useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef, type MutableRefObject } from "react";
import * as THREE from "three";

type Pointer = { x: number; y: number };

const NODE_COLORS = ["#d7c6ff", "#ff8a5c", "#8ef0d2"];
const RADIUS = 1.55;

function LoopGraph({
  pointer,
  scroll,
}: {
  pointer: MutableRefObject<Pointer>;
  scroll: MutableRefObject<number>;
}) {
  const group = useRef<THREE.Group>(null);
  const nodes = useRef<Array<THREE.Mesh | null>>([null, null, null]);
  const token = useRef<THREE.Mesh>(null);
  const satellites = useRef<THREE.Group>(null);
  const line = useMemo(() => {
    const geometry = new THREE.BufferGeometry();
    const material = new THREE.LineBasicMaterial({
      color: "#f6f1e8",
      transparent: true,
      opacity: 0.42,
    });
    return new THREE.Line(geometry, material);
  }, []);

  useEffect(() => {
    return () => {
      line.geometry.dispose();
      (line.material as THREE.Material).dispose();
    };
  }, [line]);

  useFrame(({ clock }) => {
    const t = clock.elapsedTime;
    const positions = [0, 1, 2].map((index) => {
      const angle = Math.PI / 2 + (index / 3) * Math.PI * 2 + t * 0.16;
      return new THREE.Vector3(
        Math.cos(angle) * RADIUS,
        Math.sin(angle) * RADIUS * 0.72 + Math.sin(t * 1.3 + index) * 0.05,
        Math.cos(angle) * 0.28,
      );
    });
    positions.forEach((position, index) => {
      nodes.current[index]?.position.copy(position);
    });
    line.geometry.setFromPoints([...positions, positions[0]]);
    const travel = (t * 0.22) % 3;
    const segment = Math.floor(travel);
    const along = travel - segment;
    token.current?.position.lerpVectors(positions[segment], positions[(segment + 1) % 3], along);
    if (satellites.current) satellites.current.rotation.y = t * 0.08;
    if (group.current) {
      const targetY = pointer.current.x * 0.4 + scroll.current * 0.7;
      const targetX = 0.18 + pointer.current.y * 0.22;
      group.current.rotation.y += (targetY - group.current.rotation.y) * 0.06;
      group.current.rotation.x += (targetX - group.current.rotation.x) * 0.06;
    }
  });

  return (
    <group ref={group}>
      <mesh>
        <icosahedronGeometry args={[0.34, 1]} />
        <meshStandardMaterial
          color="#f6f1e8"
          emissive="#e2ff57"
          emissiveIntensity={0.28}
          roughness={0.35}
          metalness={0.15}
        />
      </mesh>
      <mesh>
        <icosahedronGeometry args={[0.46, 1]} />
        <meshBasicMaterial color="#e2ff57" wireframe transparent opacity={0.35} />
      </mesh>
      <mesh rotation={[Math.PI / 2.15, 0.2, 0]}>
        <torusGeometry args={[1.55, 0.008, 8, 80]} />
        <meshBasicMaterial color="#f6f1e8" transparent opacity={0.28} />
      </mesh>
      <primitive object={line} />
      {NODE_COLORS.map((color, index) => (
        <mesh key={color} ref={(node) => { nodes.current[index] = node; }}>
          <sphereGeometry args={[0.2, 24, 24]} />
          <meshStandardMaterial
            color={color}
            emissive={color}
            emissiveIntensity={0.45}
            roughness={0.32}
          />
        </mesh>
      ))}
      <mesh ref={token}>
        <sphereGeometry args={[0.07, 16, 16]} />
        <meshBasicMaterial color="#e2ff57" />
      </mesh>
      <group ref={satellites}>
        {[0, 1, 2, 3, 4, 5].map((index) => {
          const angle = (index / 6) * Math.PI * 2;
          const ring = 2.15 + (index % 2) * 0.18;
          return (
            <mesh
              key={index}
              position={[Math.cos(angle) * ring, Math.sin(angle * 2) * 0.35, Math.sin(angle) * ring * 0.35]}
            >
              <sphereGeometry args={[0.045, 12, 12]} />
              <meshBasicMaterial color={NODE_COLORS[index % 3]} transparent opacity={0.85} />
            </mesh>
          );
        })}
      </group>
    </group>
  );
}

export default function HeroCanvas({
  pointer,
  scroll,
  active,
  onReady,
}: {
  pointer: MutableRefObject<Pointer>;
  scroll: MutableRefObject<number>;
  active: boolean;
  onReady: () => void;
}) {
  return (
    <Canvas
      dpr={[1, 1.5]}
      camera={{ position: [0, 0.15, 5.4], fov: 40 }}
      gl={{ alpha: true, antialias: true, powerPreference: "high-performance" }}
      frameloop={active ? "always" : "never"}
      onCreated={onReady}
      aria-hidden="true"
    >
      <ambientLight intensity={0.6} />
      <directionalLight position={[3.5, 4.5, 4]} intensity={1.35} />
      <pointLight position={[-2.5, -1.5, 2]} intensity={0.45} color="#ff8a5c" />
      <LoopGraph pointer={pointer} scroll={scroll} />
    </Canvas>
  );
}
