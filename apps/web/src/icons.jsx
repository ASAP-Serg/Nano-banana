function Svg({ children, label }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="16"
      height="16"
      aria-hidden={label ? undefined : true}
      aria-label={label}
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {children}
    </svg>
  );
}

export function IconDownload() {
  return (
    <Svg>
      <path d="M12 3v12" />
      <path d="M7 11l5 5 5-5" />
      <path d="M5 21h14" />
    </Svg>
  );
}

export function IconInfo() {
  return (
    <Svg>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 10v6" />
      <path d="M12 7h.01" />
    </Svg>
  );
}

export function IconToForm() {
  return (
    <Svg>
      <path d="M4 12h12" />
      <path d="M10 6l6 6-6 6" />
      <path d="M20 5v14" />
    </Svg>
  );
}

export function IconTrash() {
  return (
    <Svg>
      <path d="M4 7h16" />
      <path d="M9 7V5h6v2" />
      <path d="M6 7l1 14h10l1-14" />
    </Svg>
  );
}

export function IconRefresh() {
  return (
    <Svg>
      <path d="M20 12a8 8 0 1 1-2.3-5.7" />
      <path d="M20 4v6h-6" />
    </Svg>
  );
}

export function IconButton({ className, title, onClick, children, type = "button" }) {
  return (
    <button type={type} className={className} title={title} aria-label={title} onClick={onClick}>
      {children}
      <span className="visually-hidden">{title}</span>
    </button>
  );
}

const SERVICE_ICONS = {
  moonez: (
    <svg viewBox="0 0 44 44" aria-hidden="true">
      <rect x="4" y="4" width="36" height="36" rx="10" fill="currentColor" opacity="0.12" />
      <path
        d="M22 10c4 6 9 8 9 14a9 9 0 1 1-18 0c0-6 5-8 9-14z"
        fill="currentColor"
        opacity="0.9"
      />
    </svg>
  ),
  google_gemini: (
    <svg viewBox="0 0 44 44" aria-hidden="true">
      <rect x="4" y="4" width="36" height="36" rx="10" fill="currentColor" opacity="0.12" />
      <path d="M22 12l2.4 7.2H32l-6 4.4 2.3 7.2L22 26.4 15.7 30.8l2.3-7.2-6-4.4h7.6z" fill="currentColor" />
    </svg>
  ),
  your_account: (
    <svg viewBox="0 0 44 44" aria-hidden="true">
      <rect x="4" y="4" width="36" height="36" rx="10" fill="currentColor" opacity="0.12" />
      <circle cx="22" cy="18" r="6" fill="currentColor" />
      <path d="M10 34c2.5-6 7-9 12-9s9.5 3 12 9" fill="currentColor" />
    </svg>
  ),
};

export function ServiceIcon({ id }) {
  return <span className="service-status-card__icon">{SERVICE_ICONS[id] || SERVICE_ICONS.moonez}</span>;
}
