import { useState } from "react";
import { api } from "../api.js";
import { toast } from "../toast.js";
import Modal from "./Modal.jsx";

export default function AccountModal({ user, onClose, onUsernameChanged }) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [username, setUsername] = useState(user?.username || "");
  const hasPassword = user?.has_password !== false;

  async function savePassword(e) {
    e.preventDefault();
    try {
      await api.changePassword(currentPassword, newPassword);
      setCurrentPassword("");
      setNewPassword("");
      toast("Пароль изменён");
    } catch (err) {
      toast(err.message, "error");
    }
  }

  async function saveUsername(e) {
    e.preventDefault();
    try {
      const next = await api.changeUsername(hasPassword ? currentPassword : "", username.trim());
      onUsernameChanged(next);
      toast("Имя изменено");
    } catch (err) {
      toast(err.message, "error");
    }
  }

  async function revokeDevices() {
    try {
      await api.revokeTrustedDevices();
      toast("Доверенные устройства сброшены — при следующем входе снова нужен 2FA");
    } catch (err) {
      toast(err.message, "error");
    }
  }

  return (
    <Modal title="Аккаунт" onClose={onClose}>
      {user?.google_linked && (
        <p className="small text-muted mb-3">Аккаунт связан с Google{hasPassword ? " и паролем" : ""}.</p>
      )}
      {hasPassword ? (
        <>
          <p className="small text-muted">Текущий пароль — тот, которым входите. Код 2FA сюда не нужен.</p>
          <form onSubmit={savePassword} className="mb-4">
            <label className="form-label">Сменить пароль</label>
            <input
              className="form-control mb-2"
              type="password"
              autoComplete="current-password"
              placeholder="Текущий пароль"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              required
            />
            <input
              className="form-control mb-2"
              type="password"
              autoComplete="new-password"
              placeholder="Новый, от 10 символов"
              minLength={10}
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
            />
            <button className="btn btn-primary">Сохранить пароль</button>
          </form>
        </>
      ) : (
        <p className="small text-muted mb-3">Вход только через Google — локального пароля нет.</p>
      )}
      <form onSubmit={saveUsername} className="mb-4">
        <label className="form-label">Сменить имя</label>
        {hasPassword && (
          <input
            className="form-control mb-2"
            type="password"
            autoComplete="current-password"
            placeholder="Текущий пароль"
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
            required
          />
        )}
        <input
          className="form-control mb-2"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          minLength={3}
          maxLength={32}
          required
        />
        <button className="btn btn-outline-primary">Сохранить имя</button>
      </form>
      {user?.totp_enabled && (
        <div className="border-top pt-3">
          <p className="small text-muted mb-2">Сбросить «запомнить устройство» на всех браузерах.</p>
          <button type="button" className="btn btn-outline-danger btn-sm" onClick={revokeDevices}>
            Забыть все доверенные устройства
          </button>
        </div>
      )}
    </Modal>
  );
}
