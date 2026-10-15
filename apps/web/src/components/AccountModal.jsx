import { useState } from "react";
import { api } from "../api.js";
import { toast } from "../toast.js";
import Modal from "./Modal.jsx";

export default function AccountModal({ user, onClose, onUsernameChanged }) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [username, setUsername] = useState(user?.username || "");

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
      const next = await api.changeUsername(currentPassword, username.trim());
      onUsernameChanged(next);
      toast("Имя изменено");
    } catch (err) {
      toast(err.message, "error");
    }
  }

  return (
    <Modal title="Аккаунт" onClose={onClose}>
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
      <form onSubmit={saveUsername}>
        <label className="form-label">Сменить имя</label>
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
    </Modal>
  );
}
