import { useEffect, useMemo, useState } from "react";

/** Split stored `nick#1234` into parts; ignore invalid tag. */
export function splitDiscordUsername(value) {
  const text = String(value || "").trim();
  const idx = text.lastIndexOf("#");
  if (idx <= 0) return { nick: text, tag: "" };
  const nick = text.slice(0, idx);
  const tag = text.slice(idx + 1).replace(/\D/g, "").slice(0, 4);
  return { nick, tag };
}

export function composeDiscordUsername(nick, tag) {
  const n = String(nick || "").trim();
  const t = String(tag || "").replace(/\D/g, "").slice(0, 4);
  return t.length === 4 ? `${n}#${t}` : n;
}

/**
 * Discord-style: [nick input][# hardcoded][4 digits]
 * Writes composed value into hidden input name={name} when provided.
 */
export default function DiscordUsernameField({
  name = "username",
  nick: nickProp,
  tag: tagProp,
  defaultNick = "",
  defaultTag = "",
  onChange,
  disabled = false,
  required = true,
  className = "nb-auth-input",
  autoFocus = false,
  idPrefix = "discord-user",
}) {
  const controlled = nickProp !== undefined || tagProp !== undefined;
  const [nickLocal, setNickLocal] = useState(defaultNick);
  const [tagLocal, setTagLocal] = useState(defaultTag);

  const nick = controlled ? nickProp ?? "" : nickLocal;
  const tag = controlled ? tagProp ?? "" : tagLocal;

  useEffect(() => {
    if (!controlled && (defaultNick || defaultTag)) {
      setNickLocal(defaultNick || "");
      setTagLocal(defaultTag || "");
    }
  }, [controlled, defaultNick, defaultTag]);

  const composed = useMemo(() => composeDiscordUsername(nick, tag), [nick, tag]);

  function setNick(next) {
    if (!controlled) setNickLocal(next);
    onChange?.({ nick: next, tag, username: composeDiscordUsername(next, tag) });
  }

  function setTag(next) {
    const digits = String(next || "").replace(/\D/g, "").slice(0, 4);
    if (!controlled) setTagLocal(digits);
    onChange?.({ nick, tag: digits, username: composeDiscordUsername(nick, digits) });
  }

  return (
    <div className="nb-discord-user">
      <input
        id={`${idPrefix}-nick`}
        className={`${className} nb-discord-nick`}
        type="text"
        value={nick}
        onChange={(e) => setNick(e.target.value)}
        placeholder="ник"
        required={required}
        minLength={2}
        maxLength={28}
        autoComplete="username"
        autoCapitalize="none"
        spellCheck={false}
        disabled={disabled}
        autoFocus={autoFocus}
      />
      <span className="nb-discord-hash" aria-hidden="true">
        #
      </span>
      <input
        id={`${idPrefix}-tag`}
        className={`${className} nb-discord-tag`}
        type="text"
        inputMode="numeric"
        pattern="\d{4}"
        value={tag}
        onChange={(e) => setTag(e.target.value)}
        placeholder="0000"
        required={required}
        minLength={4}
        maxLength={4}
        autoComplete="off"
        disabled={disabled}
        aria-label="4 цифры тега"
      />
      {name ? <input type="hidden" name={name} value={composed} readOnly /> : null}
    </div>
  );
}
