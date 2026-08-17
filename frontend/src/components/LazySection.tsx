/* Render a section only once it is near the viewport.
 *
 * This is what makes "no clicking, just scroll" affordable. A day holds up to
 * five games and each carries six sections; mounting all of them at once is
 * thirty concurrent requests before a single pixel is useful. Tabs solved that
 * by making the reader do the deferring by hand.
 *
 * The observer defers instead. Sections mount slightly before they are reached,
 * so by the time one is scrolled to it has already loaded, and nothing below
 * the fold costs anything.
 *
 * The placeholder reserves the section's height. Without it every mount would
 * shift the page under the reader's scroll position — the classic symptom of
 * lazy content, and worse than the loading it avoids.
 */

import { useEffect, useRef, useState, type ReactNode } from "react";

export default function LazySection({
  children,
  minHeight = 320,
  /** How far ahead to start loading. A screen's worth is enough to feel instant. */
  rootMargin = "600px",
}: {
  children: ReactNode;
  minHeight?: number;
  rootMargin?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (visible) return;
    const node = ref.current;
    if (!node) return;

    // No IntersectionObserver (old browser, some test runners): render
    // everything rather than render nothing. Degrading to eager is slower;
    // degrading to blank is broken.
    if (typeof IntersectionObserver === "undefined") {
      setVisible(true);
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { rootMargin },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [visible, rootMargin]);

  return (
    <div ref={ref} style={{ minHeight: visible ? undefined : minHeight }}>
      {visible ? children : <div className="skeleton" style={{ height: minHeight - 16 }} />}
    </div>
  );
}
