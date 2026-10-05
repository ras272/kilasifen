'use client';

export function AsciiArt({ className }: { className?: string }) {
  return (
    <video
      aria-hidden="true"
      autoPlay
      className={className}
      loop
      muted
      playsInline
      poster="https://assets.21st.dev/ascii-recipes/thumbnails/user_2xJxXqdwWohYrdd6fiMYrS9hbmO/eae3b158-33e1-442d-8e17-3b4fb6656a7f.webp"
      src="https://assets.21st.dev/ascii-recipes/videos/user_2xJxXqdwWohYrdd6fiMYrS9hbmO/2e358adb-cfc9-4ec4-a600-1abc8836f02b.mp4"
      style={{
        display: 'block',
        width: '100%',
        height: '100%',
        objectFit: 'cover',
      }}
    />
  );
}
