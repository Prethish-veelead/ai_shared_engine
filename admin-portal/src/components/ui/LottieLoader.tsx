"use client";

import React from "react";
import { DotLottiePlayer } from "@dotlottie/react-player";
import "@dotlottie/react-player/dist/index.css";

interface LottieLoaderProps {
  message?: string;
  size?: number;
}

export function LottieLoader({ message = "Loading...", size = 200 }: LottieLoaderProps) {
  return (
    <div className="flex h-full w-full flex-col items-center justify-center p-8 text-center animate-in fade-in duration-500">
      <div 
        style={{ width: size, height: size }} 
        className="flex items-center justify-center relative"
      >
        <DotLottiePlayer
          src="/login.json"
          autoplay
          loop
          className="w-full h-full object-contain"
        />
      </div>
      {message && (
        <p className="mt-6 text-sm font-medium text-gray-500 dark:text-gray-400 animate-pulse">
          {message}
        </p>
      )}
    </div>
  );
}
