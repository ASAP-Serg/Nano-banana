import { useEffect } from "react";
import { downloadImage } from "../toast.js";
import { IconDownload } from "../icons.jsx";

export default function Lightbox({ items, index, onClose, onIndex }) {
  const item = items[index];

  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowLeft") onIndex(Math.max(0, index - 1));
      if (e.key === "ArrowRight") onIndex(Math.min(items.length - 1, index + 1));
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener("keydown", onKey);
    };
  }, [index, items.length, onClose, onIndex]);

  if (!item) return null;

  return (
    <div className="fullscreen-image-modal" role="dialog" onClick={onClose}>
      <div
        style={{
          position: "relative",
          maxWidth: "95%",
          maxHeight: "95%",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          cursor: "default",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <button type="button" className="btn btn-sm btn-light position-absolute fullscreen-close-btn" onClick={onClose}>
          ×
        </button>
        {index > 0 && (
          <button
            type="button"
            className="btn btn-light fullscreen-arrow"
            style={{ position: "absolute", left: -56, top: "40%" }}
            onClick={() => onIndex(index - 1)}
          >
            ‹
          </button>
        )}
        {index < items.length - 1 && (
          <button
            type="button"
            className="btn btn-light fullscreen-arrow"
            style={{ position: "absolute", right: -56, top: "40%" }}
            onClick={() => onIndex(index + 1)}
          >
            ›
          </button>
        )}
        <img src={item.result_url} alt="" style={{ maxWidth: "100%", maxHeight: "75vh", objectFit: "contain", borderRadius: 8 }} />
        <div className="text-light text-center mt-2" style={{ maxWidth: "80%", fontSize: "0.9rem", opacity: 0.8 }}>
          {item.prompt}
        </div>
        <div className="text-light text-center mt-1" style={{ fontSize: "0.85rem", opacity: 0.7 }}>
          {index + 1} / {items.length}
        </div>
        <button type="button" className="btn btn-sm btn-success mt-3 d-inline-flex align-items-center gap-2" onClick={() => downloadImage(item.result_url, item.prompt)}>
          <IconDownload />
          Скачать
        </button>
      </div>
    </div>
  );
}
