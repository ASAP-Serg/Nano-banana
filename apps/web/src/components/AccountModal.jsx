import { useState } from "react";
import { api } from "../api.js";
import { toast } from "../toast.js";
import Modal from "./Modal.jsx";

export default function AccountModal({ user, onClose, onUsernameChanged, onUserUpdated, onDeleted }) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [username, setUsername] = useState(user?.username || "");
  const [email, setEmail] = useState(user?.email || "");
  const [deletePassword, setDeletePassword] = useState("");
  const [deleteConfirm, setDeleteConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const hasPassword = user?.has_password !== false;
  const emailOk = Boolean(user?.email_verified) || Boolean(user?.google_linked);

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

  async function saveEmail(e) {
    e.preventDefault();
    setBusy(true);
    try {
      const next = await api.updateEmail(email.trim(), hasPassword ? currentPassword : "");
      onUserUpdated?.(next);
      toast("Письмо с подтверждением отправлено");
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setBusy(false);
    }
  }

  async function resendVerify() {
    setBusy(true);
    try {
      await api.resendVerification(user.email);
      toast("Если аккаунт не подтверждён — письмо отправлено");
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setBusy(false);
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

  async function deleteAccount(e) {
    e.preventDefault();
    if (!window.confirm("Удалить аккаунт навсегда? Генерации и файлы тоже будут удалены.")) return;
    setBusy(true);
    try {
      await api.deleteAccount(
        hasPassword
          ? { current_password: deletePassword, confirm: "" }
          : { current_password: "", confirm: deleteConfirm.trim() }
      );
      toast("Аккаунт удалён");
      onDeleted?.();
      onClose();
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Аккаунт" onClose={onClose}>
      {user?.google_linked && (
        <p className="small text-muted mb-3">Аккаунт связан с Google{hasPassword ? " и паролем" : ""}.</p>
      )}
      {!emailOk && (
        <div className="alert alert-warning py-2 small">
          Подтвердите email — без этого генерации недоступны.
          <button type="button" className="btn btn-link btn-sm p-0 ms-2" disabled={busy} onClick={resendVerify}>
            Отправить письмо снова
          </button>
        </div>
      )}
      {user && !user.is_admin && user.is_approved === false && (
        <div className="alert alert-info py-2 small">Аккаунт ждёт подтверждения администратором.</div>
      )}

      <form onSubmit={saveEmail} className="mb-4">
        <label className="form-label">Email {emailOk ? "" : "(нужно подтвердить)"}</label>
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
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          autoComplete="email"
        />
        <button className="btn btn-outline-primary" disabled={busy}>
          Сохранить и отправить подтверждение
        </button>
      </form>

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
        <div className="border-top pt-3 mb-4">
          <p className="small text-muted mb-2">Сбросить «запомнить устройство» на всех браузерах.</p>
          <button type="button" className="btn btn-outline-danger btn-sm" onClick={revokeDevices}>
            Забыть все доверенные устройства
          </button>
        </div>
      )}
      <div className="border-top pt-3">
        <h6 className="text-danger">Удалить аккаунт</h6>
        <p className="small text-muted">Безвозвратно: профиль, генерации и файлы.</p>
        <form onSubmit={deleteAccount}>
          {hasPassword ? (
            <input
              className="form-control mb-2"
              type="password"
              autoComplete="current-password"
              placeholder="Текущий пароль"
              value={deletePassword}
              onChange={(e) => setDeletePassword(e.target.value)}
              required
            />
          ) : (
            <input
              className="form-control mb-2"
              placeholder={`Введите имя «${user?.username || ""}» для подтверждения`}
              value={deleteConfirm}
              onChange={(e) => setDeleteConfirm(e.target.value)}
              required
            />
          )}
          <button type="submit" className="btn btn-danger btn-sm" disabled={busy}>
            Удалить навсегда
          </button>
        </form>
      </div>
    </Modal>
  );
}
