import { useState } from "react";
import Modal from "./Modal.jsx";

function PasswordField({ name, placeholder, minLength }) {
  const [visible, setVisible] = useState(false);
  return (
    <div className="input-group mb-3">
      <input
        className="form-control"
        name={name}
        type={visible ? "text" : "password"}
        placeholder={placeholder}
        required
        minLength={minLength}
      />
      <button type="button" className="btn btn-outline-secondary" onClick={() => setVisible((v) => !v)}>
        {visible ? "Скрыть" : "Показать"}
      </button>
    </div>
  );
}

export default function AuthModals({
  showLogin,
  showRegister,
  onCloseLogin,
  onCloseRegister,
  onOpenRegister,
  onLogin,
  onRegister,
}) {
  return (
    <>
      {showLogin && (
        <Modal title="Вход" onClose={onCloseLogin}>
          <form onSubmit={onLogin}>
            <input className="form-control mb-2" name="username" placeholder="Имя или email" required />
            <PasswordField name="password" placeholder="Пароль" />
            <input
              className="form-control mb-1"
              name="totp"
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              placeholder="Код 2FA (если включён)"
            />
            <p className="form-text text-muted mb-3">Если на аккаунте нет 2FA — оставьте поле пустым.</p>
            <button className="btn btn-primary w-100">Войти</button>
            <button type="button" className="btn btn-link w-100" onClick={onOpenRegister}>
              Нет аккаунта? Регистрация
            </button>
          </form>
        </Modal>
      )}
      {showRegister && (
        <Modal title="Регистрация" onClose={onCloseRegister}>
          <form onSubmit={onRegister}>
            <input
              className="form-control mb-2"
              name="username"
              placeholder="Имя: 3–32 символа, буквы и цифры"
              required
              minLength={3}
              maxLength={32}
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
              title="3–32 символа, буквы и цифры, внутри можно . _ -"
            />
            <input className="form-control mb-2" name="email" type="email" placeholder="Email" required />
            <PasswordField name="password" placeholder="Пароль от 10 символов" minLength={10} />
            <button className="btn btn-primary w-100">Создать аккаунт</button>
          </form>
        </Modal>
      )}
    </>
  );
}
