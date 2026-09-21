export default function Navbar({
  theme,
  onToggleTheme,
  user,
  onLogin,
  onKeys,
  onAdmin,
  onLogout,
}) {
  return (
    <nav className="navbar navbar-expand-lg navbar-dark bg-dark">
      <div className="container">
        <a className="navbar-brand" href="/">
          🍌 Nano Banana
        </a>
        <button className="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav">
          <span className="navbar-toggler-icon" />
        </button>
        <div className="collapse navbar-collapse" id="navbarNav">
          <ul className="navbar-nav ms-auto">
            <li className="nav-item">
              <a className="nav-link active" href="/">
                Главная
              </a>
            </li>
          </ul>
          <div className="d-flex align-items-center">
            <div className="form-check form-switch me-3 mb-0">
              <input
                className="form-check-input"
                type="checkbox"
                checked={theme === "light"}
                onChange={onToggleTheme}
                id="themeSwitch"
              />
              <label className="form-check-label text-light" htmlFor="themeSwitch">
                {theme === "dark" ? "Тёмная" : "Светлая"}
              </label>
            </div>
            {!user ? (
              <button className="btn btn-outline-light" onClick={onLogin}>
                Войти
              </button>
            ) : (
              <div className="dropdown ms-2">
                <button className="btn btn-outline-light dropdown-toggle" data-bs-toggle="dropdown" type="button">
                  {user.username}
                </button>
                <ul className="dropdown-menu dropdown-menu-end">
                  <li>
                    <button className="dropdown-item" onClick={onKeys}>
                      API ключи
                    </button>
                  </li>
                  {user.is_admin && (
                    <li>
                      <button className="dropdown-item" onClick={onAdmin}>
                        Админ-панель
                      </button>
                    </li>
                  )}
                  <li>
                    <button className="dropdown-item" onClick={onLogout}>
                      Выйти
                    </button>
                  </li>
                </ul>
              </div>
            )}
          </div>
        </div>
      </div>
    </nav>
  );
}
