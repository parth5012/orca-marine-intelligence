'use client';

import React from 'react';
import { motion } from 'framer-motion';

export const LivingOceanBackground: React.FC = () => {
  // Pre-configured floating bubble particle settings
  const bubbles = [
    { id: 1, left: '8%', size: 6, duration: 19, delay: 0 },
    { id: 2, left: '18%', size: 10, duration: 23, delay: 4 },
    { id: 3, left: '29%', size: 4, duration: 16, delay: 1 },
    { id: 4, left: '42%', size: 8, duration: 26, delay: 7 },
    { id: 5, left: '55%', size: 12, duration: 20, delay: 2 },
    { id: 6, left: '68%', size: 5, duration: 22, delay: 5 },
    { id: 7, left: '81%', size: 9, duration: 18, delay: 1.5 },
    { id: 8, left: '92%', size: 6, duration: 25, delay: 3 }
  ];

  // School of fish offsets
  const fishSchool = [
    { x: 0, y: 0, scale: 1 },
    { x: -22, y: -8, scale: 0.85 },
    { x: -18, y: 12, scale: 0.9 },
    { x: -38, y: 3, scale: 0.75 },
    { x: -44, y: -15, scale: 0.7 },
    { x: -60, y: -5, scale: 0.8 },
    { x: -55, y: 18, scale: 0.65 },
    { x: -78, y: 8, scale: 0.6 }
  ];

  return (
    <div className="fixed inset-0 pointer-events-none z-0 overflow-hidden select-none">
      {/* Ambient Underwater Lighting Pools */}
      <div className="absolute top-10 left-1/4 w-[600px] h-[350px] bg-gradient-to-b from-cyan-400/10 via-sky-500/05 to-transparent rounded-full blur-3xl" />
      <div className="absolute bottom-20 right-10 w-[550px] h-[450px] bg-teal-500/08 rounded-full blur-3xl" />
      <div className="absolute top-1/2 right-1/3 w-[450px] h-[450px] bg-cyan-600/06 rounded-full blur-3xl" />

      {/* 🐋 1. DISTANT BLUE WHALE SILHOUETTE (Top / Deep Background) */}
      <motion.div
        className="absolute top-[8%] opacity-[0.09]"
        initial={{ x: '-250px' }}
        animate={{
          x: ['-250px', '100vw'],
          y: [0, -12, 5, -8, 0]
        }}
        transition={{
          x: { duration: 58, repeat: Infinity, ease: 'linear' },
          y: { duration: 14, repeat: Infinity, ease: 'easeInOut' }
        }}
      >
        <svg width="220" height="75" viewBox="0 0 220 75" fill="#0284c7">
          {/* Whale Body */}
          <path d="M 20,40 C 40,15 90,8 140,18 C 175,25 198,35 215,38 C 210,44 195,47 175,48 C 140,50 95,55 50,50 C 32,48 22,45 20,40 Z" />
          {/* Tail Flukes */}
          <path d="M 20,40 C 12,32 0,22 4,18 C 8,24 14,32 18,38 C 12,44 4,55 0,58 C 4,54 12,46 20,40 Z" />
          {/* Pectoral Flipper */}
          <path d="M 95,45 C 90,62 80,70 75,68 C 78,60 88,48 95,45 Z" />
        </svg>
      </motion.div>

      {/* 🐬 2. DOLPHINS PAIR SILHOUETTES (Upper-Middle) */}
      <motion.div
        className="absolute top-[28%] opacity-[0.12]"
        initial={{ x: '-160px' }}
        animate={{
          x: ['-160px', '100vw'],
          y: [0, -25, 10, -20, 0]
        }}
        transition={{
          x: { duration: 36, repeat: Infinity, delay: 8, ease: 'linear' },
          y: { duration: 6, repeat: Infinity, ease: 'easeInOut' }
        }}
      >
        <div className="relative">
          {/* Lead Dolphin */}
          <svg width="85" height="40" viewBox="0 0 85 40" fill="#0891b2">
            <path d="M 0,20 C 15,8 35,5 55,12 C 70,18 80,18 85,20 C 78,24 62,26 48,24 C 32,22 16,25 0,20 Z" />
            {/* Dorsal Fin */}
            <path d="M 38,10 C 44,0 48,2 45,10 Z" />
            {/* Flukes */}
            <path d="M 0,20 L -8,12 L -5,20 L -8,28 Z" />
          </svg>
          {/* Companion Dolphin */}
          <svg width="65" height="30" viewBox="0 0 85 40" fill="#0891b2" className="absolute -bottom-4 -left-8 opacity-80">
            <path d="M 0,20 C 15,8 35,5 55,12 C 70,18 80,18 85,20 C 78,24 62,26 48,24 C 32,22 16,25 0,20 Z" />
            <path d="M 38,10 C 44,0 48,2 45,10 Z" />
            <path d="M 0,20 L -8,12 L -5,20 L -8,28 Z" />
          </svg>
        </div>
      </motion.div>

      {/* 🐟 3. SCHOOL OF FISH SILHOUETTES (Middle Stream) */}
      <motion.div
        className="absolute top-[48%] opacity-[0.14]"
        initial={{ x: '-200px' }}
        animate={{
          x: ['-200px', '100vw'],
          y: [0, 15, -10, 8, 0]
        }}
        transition={{
          x: { duration: 30, repeat: Infinity, delay: 3, ease: 'linear' },
          y: { duration: 8, repeat: Infinity, ease: 'easeInOut' }
        }}
      >
        <div className="relative">
          {fishSchool.map((f, idx) => (
            <svg
              key={idx}
              width="28"
              height="14"
              viewBox="0 0 28 14"
              fill="#0284c7"
              className="absolute"
              style={{
                transform: `translate(${f.x}px, ${f.y}px) scale(${f.scale})`
              }}
            >
              <path d="M 0,7 C 8,1 18,1 24,7 C 18,13 8,13 0,7 Z" />
              <path d="M 23,7 L 28,2 L 26,7 L 28,12 Z" />
            </svg>
          ))}
        </div>
      </motion.div>

      {/* 🐢 4. SEA TURTLE SILHOUETTE (Distant Middle-Lower) */}
      <motion.div
        className="absolute top-[64%] opacity-[0.11]"
        initial={{ x: '100vw' }}
        animate={{
          x: ['100vw', '-150px'],
          y: [0, -10, 8, -5, 0]
        }}
        transition={{
          x: { duration: 52, repeat: Infinity, delay: 14, ease: 'linear' },
          y: { duration: 12, repeat: Infinity, ease: 'easeInOut' }
        }}
      >
        <svg width="70" height="50" viewBox="0 0 70 50" fill="#0d9488">
          {/* Shell */}
          <ellipse cx="35" cy="25" rx="20" ry="15" />
          {/* Head */}
          <ellipse cx="60" cy="25" rx="7" ry="5" />
          {/* Front Flippers */}
          <path d="M 42,12 C 48,-2 58,-2 52,12 Z" />
          <path d="M 42,38 C 48,52 58,52 52,38 Z" />
          {/* Rear Flippers */}
          <path d="M 20,15 C 12,5 18,5 20,15 Z" />
          <path d="M 20,35 C 12,45 18,45 20,35 Z" />
        </svg>
      </motion.div>

      {/* 🪼 5. FAINT JELLYFISH SILHOUETTES (Sides with Soft Glow) */}
      {/* Left Jellyfish */}
      <motion.div
        className="absolute left-[3%] top-[35%] opacity-[0.16]"
        animate={{
          y: [0, -45, 0],
          scale: [1, 1.05, 1],
          opacity: [0.12, 0.2, 0.12]
        }}
        transition={{
          duration: 16,
          repeat: Infinity,
          ease: 'easeInOut'
        }}
      >
        <svg width="60" height="90" viewBox="0 0 60 90" fill="none">
          {/* Glowing Umbrella Bell */}
          <path
            d="M 10,35 C 10,12 50,12 50,35 C 40,38 30,38 20,35 Z"
            fill="url(#jellyGlow1)"
          />
          {/* Soft Tentacles */}
          <path d="M 18,36 Q 14,55 20,75 Q 16,85 18,90" stroke="#38bdf8" strokeWidth="1.5" strokeOpacity="0.6" fill="none" />
          <path d="M 26,37 Q 30,58 24,78 Q 28,88 26,92" stroke="#22d3ee" strokeWidth="1.5" strokeOpacity="0.7" fill="none" />
          <path d="M 34,37 Q 30,56 36,76 Q 32,86 34,92" stroke="#22d3ee" strokeWidth="1.5" strokeOpacity="0.7" fill="none" />
          <path d="M 42,36 Q 46,55 40,75 Q 44,85 42,90" stroke="#38bdf8" strokeWidth="1.5" strokeOpacity="0.6" fill="none" />
          <defs>
            <radialGradient id="jellyGlow1" cx="50%" cy="40%" r="60%">
              <stop offset="0%" stopColor="#38bdf8" stopOpacity="0.7" />
              <stop offset="100%" stopColor="#0891b2" stopOpacity="0.2" />
            </radialGradient>
          </defs>
        </svg>
      </motion.div>

      {/* Right Jellyfish */}
      <motion.div
        className="absolute right-[4%] top-[50%] opacity-[0.15]"
        animate={{
          y: [0, -38, 0],
          scale: [0.95, 1.04, 0.95],
          opacity: [0.1, 0.18, 0.1]
        }}
        transition={{
          duration: 20,
          repeat: Infinity,
          delay: 5,
          ease: 'easeInOut'
        }}
      >
        <svg width="50" height="75" viewBox="0 0 60 90" fill="none">
          <path
            d="M 10,35 C 10,12 50,12 50,35 C 40,38 30,38 20,35 Z"
            fill="url(#jellyGlow2)"
          />
          <path d="M 20,36 Q 16,55 22,75" stroke="#20b2aa" strokeWidth="1.5" strokeOpacity="0.6" fill="none" />
          <path d="M 30,37 Q 34,58 28,78" stroke="#38bdf8" strokeWidth="1.5" strokeOpacity="0.7" fill="none" />
          <path d="M 40,36 Q 44,55 38,75" stroke="#20b2aa" strokeWidth="1.5" strokeOpacity="0.6" fill="none" />
          <defs>
            <radialGradient id="jellyGlow2" cx="50%" cy="40%" r="60%">
              <stop offset="0%" stopColor="#2dd4bf" stopOpacity="0.7" />
              <stop offset="100%" stopColor="#0d9488" stopOpacity="0.2" />
            </radialGradient>
          </defs>
        </svg>
      </motion.div>

      {/* 🪸 6. SUBTLE CORAL REEF & SEAWEED SILHOUETTES (Lower Edges) */}
      {/* Bottom Left Seaweed & Coral Cluster */}
      <div className="absolute bottom-0 left-0 w-72 h-40 opacity-[0.22] flex items-end">
        <svg width="240" height="150" viewBox="0 0 240 150" fill="none">
          {/* Coral Reef Structure */}
          <path d="M 0,150 L 0,110 C 15,100 25,120 40,105 C 55,90 65,115 80,100 C 95,120 110,95 130,120 C 150,110 165,130 180,150 Z" fill="#0284c7" opacity="0.5" />
          {/* Swaying Kelp Fronds Left */}
          <motion.path
            d="M 25,150 Q 15,100 30,50 Q 18,20 25,0"
            stroke="#0d9488"
            strokeWidth="5"
            strokeLinecap="round"
            fill="none"
            animate={{ d: ['M 25,150 Q 15,100 30,50 Q 18,20 25,0', 'M 25,150 Q 30,100 15,50 Q 32,20 38,0', 'M 25,150 Q 15,100 30,50 Q 18,20 25,0'] }}
            transition={{ duration: 7, repeat: Infinity, ease: 'easeInOut' }}
          />
          <motion.path
            d="M 50,150 Q 40,110 55,60 Q 42,30 50,10"
            stroke="#06b6d4"
            strokeWidth="4"
            strokeLinecap="round"
            fill="none"
            animate={{ d: ['M 50,150 Q 40,110 55,60 Q 42,30 50,10', 'M 50,150 Q 60,110 42,60 Q 58,30 62,10', 'M 50,150 Q 40,110 55,60 Q 42,30 50,10'] }}
            transition={{ duration: 9, repeat: Infinity, delay: 1, ease: 'easeInOut' }}
          />
          <motion.path
            d="M 85,150 Q 75,115 90,70 Q 78,40 85,20"
            stroke="#14b8a6"
            strokeWidth="3.5"
            strokeLinecap="round"
            fill="none"
            animate={{ d: ['M 85,150 Q 75,115 90,70 Q 78,40 85,20', 'M 85,150 Q 95,115 78,70 Q 94,40 96,20', 'M 85,150 Q 75,115 90,70 Q 78,40 85,20'] }}
            transition={{ duration: 8, repeat: Infinity, delay: 0.5, ease: 'easeInOut' }}
          />
        </svg>
      </div>

      {/* Bottom Right Seaweed & Coral Cluster */}
      <div className="absolute bottom-0 right-0 w-72 h-40 opacity-[0.2] flex items-end justify-end">
        <svg width="240" height="150" viewBox="0 0 240 150" fill="none">
          <path d="M 60,150 C 75,125 90,140 110,110 C 130,125 145,100 160,120 C 180,105 195,125 210,115 L 240,150 Z" fill="#0369a1" opacity="0.5" />
          <motion.path
            d="M 170,150 Q 180,105 165,55 Q 182,25 175,5"
            stroke="#0f766e"
            strokeWidth="4.5"
            strokeLinecap="round"
            fill="none"
            animate={{ d: ['M 170,150 Q 180,105 165,55 Q 182,25 175,5', 'M 170,150 Q 160,105 180,55 Q 162,25 160,5', 'M 170,150 Q 180,105 165,55 Q 182,25 175,5'] }}
            transition={{ duration: 8.5, repeat: Infinity, ease: 'easeInOut' }}
          />
          <motion.path
            d="M 200,150 Q 210,115 195,65 Q 212,35 205,15"
            stroke="#0284c7"
            strokeWidth="3.5"
            strokeLinecap="round"
            fill="none"
            animate={{ d: ['M 200,150 Q 210,115 195,65 Q 212,35 205,15', 'M 200,150 Q 190,115 210,65 Q 192,35 190,15', 'M 200,150 Q 210,115 195,65 Q 212,35 205,15'] }}
            transition={{ duration: 7.5, repeat: Infinity, delay: 1.5, ease: 'easeInOut' }}
          />
        </svg>
      </div>

      {/* 🫧 7. FLOATING BUBBLE PARTICLES (Rising Gently Throughout) */}
      {bubbles.map((b) => (
        <motion.div
          key={b.id}
          className="absolute rounded-full bg-gradient-to-t from-cyan-300/30 to-teal-100/50 border border-cyan-300/40 shadow-sm shadow-cyan-400/20"
          style={{
            left: b.left,
            bottom: '-25px',
            width: `${b.size}px`,
            height: `${b.size}px`
          }}
          animate={{
            y: ['0vh', '-110vh'],
            x: [0, Math.sin(b.id) * 22, 0],
            opacity: [0, 0.5, 0.7, 0]
          }}
          transition={{
            duration: b.duration,
            repeat: Infinity,
            delay: b.delay,
            ease: 'easeInOut'
          }}
        />
      ))}

      {/* 🌊 8. ANIMATED OCEAN CURRENT STREAMLINES (Background Overlay) */}
      <div className="absolute inset-0 opacity-[0.12]">
        <svg className="w-full h-full" xmlns="http://www.w3.org/2000/svg">
          <defs>
            <linearGradient id="currentLineGrad" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#0284c7" stopOpacity="0.5" />
              <stop offset="50%" stopColor="#06b6d4" stopOpacity="0.2" />
              <stop offset="100%" stopColor="#14b8a6" stopOpacity="0.5" />
            </linearGradient>
          </defs>
          <motion.path
            d="M -100,180 C 300,90 600,380 1600,180"
            fill="none"
            stroke="url(#currentLineGrad)"
            strokeWidth="2"
            animate={{ d: ['M -100,180 C 300,90 600,380 1600,180', 'M -100,210 C 300,130 600,340 1600,210', 'M -100,180 C 300,90 600,380 1600,180'] }}
            transition={{ duration: 22, repeat: Infinity, ease: 'easeInOut' }}
          />
          <motion.path
            d="M -100,580 C 400,480 800,730 1600,530"
            fill="none"
            stroke="url(#currentLineGrad)"
            strokeWidth="1.5"
            animate={{ d: ['M -100,580 C 400,480 800,730 1600,530', 'M -100,550 C 400,510 800,700 1600,550', 'M -100,580 C 400,480 800,730 1600,530'] }}
            transition={{ duration: 28, repeat: Infinity, ease: 'easeInOut' }}
          />
        </svg>
      </div>
    </div>
  );
};
