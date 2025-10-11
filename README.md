<div align="center">
  <h1>Quiz Battle 🎯</h1>
  <p>Aplicação web interativa de quizzes, desenvolvida em <b>Flask</b> com <b>HTML</b>, <b>CSS</b> e <b>JavaScript</b>, focada em autenticação, ranking e gamificação.</p>
</div>

---

## 🚀 Visão Geral

O **Quiz Battle** é um aplicativo web de quizzes com foco em desempenho, segurança e experiência do usuário.  
Ele combina recursos de **login tradicional e social (Google)**, **envio automatizado de e-mails**, e um **ranking semanal dinâmico**, tudo dentro de uma interface leve e responsiva feita com HTML, CSS e JavaScript puro.

---

## ✨ Principais Recursos

- 🧠 **Jogo de perguntas** com pontuação e feedback em tempo real  
- 🔐 **Autenticação completa**: e-mail/senha e Login com Google (OAuth2)  
- ✉️ **Envio de e-mails automáticos** (registro e redefinição de senha)  
- 🏆 **Ranking semanal** com reset automático toda segunda-feira  
- 👤 **Avatar e perfil básico** (imagem do Google se disponível)  
- 🌗 **Tema claro/escuro** e 🎵 **áudio ambiente controlável**  
- ⚙️ **Painel seguro de redefinição de senha com token assinado**

---

## 🧠 Stack Técnica

- **Backend:** Flask, Flask-Login, SQLAlchemy, Authlib, ItsDangerous  
- **Frontend:** HTML5, CSS3, JavaScript (vanilla)  
- **Banco de Dados:** SQLite (dev) / PostgreSQL (produção, via Neon)  
- **E-mail:** Flask-Mail + Gmail SMTP  
- **Hospedagem:** Railway (app) + Neon (DB)

---

## 🔐 Integrações e Segurança

- Autenticação segura com **hash de senhas (Werkzeug)**  
- Tokens de redefinição de senha com **ItsDangerous**  
- Login com **Google OAuth 2.0** e avatar automático  
- Envio de e-mails via **SMTP seguro** ou **API Brevo**  
- Separação de credenciais no **.env** e variáveis do Railway

---

## 🧩 Estrutura Lógica

A aplicação segue uma estrutura clara e modular:

- **`app.py`** → rotas, autenticação, lógica de e-mails e ranking  
- **`models.py`** → ORM SQLAlchemy (usuários, pontuações, etc.)  
- **`templates/`** → páginas HTML (Jinja2)  
- **`static/`** → CSS, JS, imagens e sons  
- **`emails/`** → templates HTML dos e-mails transacionais  

---

## 💡 Destaques Técnicos

- Sistema de ranking com cálculo automático da **próxima segunda-feira à meia-noite**  
- **Fallback inteligente** de envio de e-mails: Brevo API → SMTP → Log  
- Layout base com **header dinâmico** e controle de tema/áudio persistente  
- Preparado para deploy em **Railway**, com variáveis seguras de ambiente  

---

## 👨‍💻 Autor

**Lucas Alcântara Holanda**  
🎓 Estudante de Ciência da Computação (UNIP)  
💼 Desenvolvedor Front-End Junior
📍 Manaus, Brasil  

🔗 [LinkedIn](https://www.linkedin.com/in/lucas-alcantara-holanda/)  
🔗 [GitHub](https://github.com/lucasalc25)

---

## 🧾 Licença

Distribuído sob a licença **MIT**.  
Sinta-se à vontade para usar, estudar e se inspirar no código.

---

<div align="center">
  <sub>💡 Projeto acadêmico e de portfólio — desenvolvido com Flask e dedicação 🧩</sub>
</div>

