"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { ChevronLeft, ChevronRight, X } from "lucide-react";

// One image tile - hides itself if the URL 404s/is hotlink-blocked, and
// defers what a click does to the caller (a gallery manages the shared
// lightbox state; a lone tile could open one directly). URL passthrough
// only - this component never downloads/caches anything itself, just
// renders an <img> pointed at wherever the image already lives.
function CitationThumbnail({ src, className, onClick }: { src: string; className?: string; onClick: () => void }) {
  const [hidden, setHidden] = useState(false);
  if (hidden) return null;
  return (
    <img
      src={src}
      alt=""
      className={`${className ?? ""} cursor-zoom-in`}
      loading="lazy"
      onError={() => setHidden(true)}
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick();
        }
      }}
    />
  );
}

// A citation's image set (web bots only - see CitationGroup.images,
// bot-ui/src/lib/citations.ts): the first image renders large (the
// publisher's own declared lead image), any further ones as a small
// scrollable filmstrip below it. Clicking any tile opens the full-size
// lightbox with Prev/Next across the whole set - shared by every chat
// theme so this isn't reimplemented 4 times.
export function CitationImageGallery({
  images, className, heroClassName, thumbClassName,
}: {
  images: string[];
  className?: string;
  heroClassName?: string;
  thumbClassName?: string;
}) {
  const [openIndex, setOpenIndex] = useState<number | null>(null);
  if (images.length === 0) return null;
  const [hero, ...rest] = images;

  return (
    <div className={className}>
      <CitationThumbnail src={hero} className={heroClassName} onClick={() => setOpenIndex(0)} />
      {rest.length > 0 && (
        <div className="mt-2 flex gap-2 overflow-x-auto">
          {rest.map((src, i) => (
            <CitationThumbnail key={src} src={src} className={thumbClassName} onClick={() => setOpenIndex(i + 1)} />
          ))}
        </div>
      )}
      {openIndex !== null && (
        <Lightbox images={images} startIndex={openIndex} onClose={() => setOpenIndex(null)} />
      )}
    </div>
  );
}

// Full-size view of a citation's image set - a dark backdrop click closes,
// an explicit X button for the same, Escape as a keyboard equivalent, and
// Prev/Next (buttons + Left/Right arrow keys) when there's more than one
// image. Rendered via a portal so the message bubble's own rounded
// corners/overflow never clip it.
function Lightbox({ images, startIndex, onClose }: { images: string[]; startIndex: number; onClose: () => void }) {
  const [index, setIndex] = useState(startIndex);
  const hasMultiple = images.length > 1;
  const prev = () => setIndex((i) => (i - 1 + images.length) % images.length);
  const next = () => setIndex((i) => (i + 1) % images.length);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowLeft" && hasMultiple) prev();
      else if (e.key === "ArrowRight" && hasMultiple) next();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasMultiple, onClose]);

  return createPortal(
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/80 p-6 animate-fade-in-up"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <button
        onClick={onClose}
        aria-label="Close"
        className="absolute right-4 top-4 rounded-full bg-white/10 p-2 text-white hover:bg-white/20 transition-colors"
      >
        <X className="h-5 w-5" />
      </button>

      {hasMultiple && (
        <button
          onClick={(e) => { e.stopPropagation(); prev(); }}
          aria-label="Previous image"
          className="absolute left-4 rounded-full bg-white/10 p-2 text-white hover:bg-white/20 transition-colors"
        >
          <ChevronLeft className="h-6 w-6" />
        </button>
      )}

      <img
        src={images[index]}
        alt=""
        onClick={(e) => e.stopPropagation()}
        className="max-h-[90vh] max-w-[90vw] rounded-lg object-contain shadow-2xl cursor-default"
      />

      {hasMultiple && (
        <button
          onClick={(e) => { e.stopPropagation(); next(); }}
          aria-label="Next image"
          className="absolute right-4 rounded-full bg-white/10 p-2 text-white hover:bg-white/20 transition-colors"
        >
          <ChevronRight className="h-6 w-6" />
        </button>
      )}

      {hasMultiple && (
        <div className="absolute bottom-4 rounded-full bg-white/10 px-3 py-1 text-xs font-medium text-white tabular-nums">
          {index + 1} / {images.length}
        </div>
      )}
    </div>,
    document.body
  );
}
