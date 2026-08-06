"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import Lottie from "lottie-react";
import { BASE_PATH } from "@/lib/basePath";

export default function NotFound() {
  const [animationData, setAnimationData] = useState<object | null>(null);

  useEffect(() => {
    fetch(`${BASE_PATH}/404-error.json`)
      .then((res) => res.json())
      .then(setAnimationData)
      .catch(() => setAnimationData(null));
  }, []);

  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 px-6 py-12 text-center">
      <div className="w-full max-w-sm">
        {animationData && <Lottie animationData={animationData} loop autoplay />}
      </div>
      <h1 className="text-xl font-bold text-navy dark:text-white">Page not found</h1>
      <p className="max-w-md text-sm text-gray-500 dark:text-gray-400">
        The page you&apos;re looking for doesn&apos;t exist or may have been moved.
      </p>
      <Link
        href="/"
        className="mt-2 inline-flex items-center gap-2 rounded-full border border-orange bg-orange px-5 py-2 text-sm font-semibold text-white shadow-md transition-all hover:bg-orange-hover"
      >
        Back to Dashboard
      </Link>
    </div>
  );
}
