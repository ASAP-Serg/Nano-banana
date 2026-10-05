import { useEffect, useState } from "react";
import { api } from "../api.js";
import { toast } from "../toast.js";
import Modal from "./Modal.jsx";

export default function TotpSetup({ onClose, onEnabled }) {
  const [secret, setSecret] = useState("");
  const [otpauth, setOtpauth] = useState("");
  const [qrDataUrl, setQrDataUrl] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await api.totpBegin();
        if (cancelled) return;
        setSecret(data.secret || "");
        setOtpauth(data.otpauth_url || "");
        setQrDataUrl(data.qr_data_url || "");
      } catch (err) {
        if (cancelled) return;
        toast(err.message, "error");
        onClose();
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function onSubmit(e) {
    e.preventDefault();
    setBusy(true);
    try {
      await api.totpConfirm(code);
      toast("Двухфакторная аутентификация включена");
      onEnabled();
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setBusy(false);
    }
  }

  async function copy(text, label) {
    try {
      await navigator.clipboard.writeText(text);
      toast(`${label} скопирован`);
    } catch {
      toast("Не удалось скопировать", "error");
    }
  }

  return (
    <Modal title="Двухфакторная аутентификация" onClose={onClose}>
      <p className="small text-muted">
        Сканируйте QR в Google Authenticator, Authy или другом приложении, затем введите код из 6 цифр.
        Без этого админка недоступна.
      </p>
      {secret ? (
        <>
          {qrDataUrl ? (
            <div className="text-center mb-3">
              <img
                src={qrDataUrl}
                alt="QR для настройки 2FA"
                width={240}
                height={240}
                style={{ background: "#fff", borderRadius: 8, padding: 8 }}
              />
            </div>
          ) : (
            <div className="text-center py-2 small text-muted">QR недоступен — используйте ключ ниже</div>
          )}
          <details className="mb-3">
            <summary className="small text-muted" style={{ cursor: "pointer" }}>
              Не сканируется? Показать ключ
            </summary>
            <label className="form-label small mt-2">Секрет</label>
            <div className="input-group mb-2">
              <input className="form-control font-monospace" readOnly value={secret} />
              <button type="button" className="btn btn-outline-secondary" onClick={() => copy(secret, "Секрет")}>
                Копировать
              </button>
            </div>
            <label className="form-label small">otpauth ссылка</label>
            <div className="input-group">
              <input className="form-control font-monospace small" readOnly value={otpauth} />
              <button type="button" className="btn btn-outline-secondary" onClick={() => copy(otpauth, "Ссылка")}>
                Копировать
              </button>
            </div>
          </details>
          <form onSubmit={onSubmit}>
            <input
              className="form-control mb-2"
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              placeholder="Код из приложения"
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
              required
            />
            <button className="btn btn-primary w-100" disabled={busy || code.length !== 6}>
              Подтвердить
            </button>
          </form>
        </>
      ) : (
        <div className="text-center py-3">Загрузка…</div>
      )}
    </Modal>
  );
}
