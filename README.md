# up-mines_bot

A Telegram bot tailored for fetching, processing, and delivering mining-related data for **Uttar Pradesh**. The bot interacts with users to collect input, retrieves relevant entries, processes them, and generates downloadable PDFs — all within Telegram.

---

##  Features

- **Interactive conversation flow**: Seamless prompts guiding users through data inputs.
- **Custom data fetching**: Collects information based on user-provided start/end numbers and district.
- **Automated portal login & processing**: Handles background login and task execution on mining portals.
- **PDF generation & delivery**: Automatically converts the results into PDFs and allows users to download them via Telegram.
- **Session handling**: Supports “restart” and “exit” options to manage user sessions effectively.

---

##  Repository Structure

| File / Directory    | Description |
|---------------------|-------------|
| `bot.py`            | Main bot logic — user interaction, data fetching, callback handling, PDF generation, and Telegram communication. |
| `mp_mining.py` (or similar) | Script/module for mining data retrieval and processing (e.g., web scraping, API calls). |
| `requirements.txt`  | Lists Python dependencies for easy environment setup. |
| `.gitignore`        | Specifies files and directories to be ignored by Git (e.g., virtual environments, temporary files, PDFs). |
| `pdf/` (optional)   | Directory where generated PDF files are saved before delivery. |

---

##  Getting Started

1. **Clone the repository**
   ```bash
   git clone https://github.com/hideepakgupta2000/up-mines_bot.git
   cd up-mines_bot
