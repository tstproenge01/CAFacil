import os, re, sys, threading, subprocess, queue
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

PORTAL = "https://caepi.trabalho.gov.br/internet/ConsultaCAInternet.aspx"
OUT_DIR = Path.home() / "Documents" / "Certificados CA"

def safe_name(value):
    return re.sub(r"[^0-9A-Za-z_-]+", "_", value).strip("_") or "CA"

def launch_edge(playwright):
    # Usa o Microsoft Edge instalado no Windows; não baixa Chromium.
    try:
        return playwright.chromium.launch(channel="msedge", headless=True)
    except Exception as exc:
        raise RuntimeError(
            "Não consegui iniciar o Microsoft Edge. Verifique se ele está instalado e atualizado. "
            "Detalhe: " + str(exc)
        )

def locate_ca_field(page):
    # Primeiro tenta o rótulo visível; depois usa o campo de texto da página oficial.
    candidates = [
        page.get_by_label(re.compile(r"N.? do CA", re.I)),
        page.locator("input[type='text']"),
    ]
    for locator in candidates:
        try:
            if locator.count():
                return locator.first
        except Exception:
            pass
    raise RuntimeError("Não encontrei o campo 'Nº do CA' no portal. O site pode ter mudado.")

def click_consult(page):
    for locator in [
        page.get_by_role("button", name=re.compile(r"Consultar", re.I)),
        page.get_by_role("input", name=re.compile(r"Consultar", re.I)),
        page.locator("input[type='submit'][value*='Consultar' i]"),
        page.get_by_text(re.compile(r"^Consultar$", re.I)),
    ]:
        try:
            if locator.count():
                locator.first.click(timeout=10000)
                return
        except Exception:
            continue
    raise RuntimeError("Não encontrei o botão Consultar no portal.")

def query_ca(ca, force_update, log):
    from playwright.sync_api import sync_playwright
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = OUT_DIR / f"CA_{safe_name(ca)}.pdf"
    if pdf_path.exists() and not force_update:
        return f"CA {ca}: já existe PDF salvo; ignorado para evitar download repetido."

    with sync_playwright() as p:
        browser = launch_edge(p)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        try:
            page.goto(PORTAL, wait_until="domcontentloaded", timeout=60000)
            field = locate_ca_field(page)
            field.fill(ca)
            click_consult(page)
            try:
                page.wait_for_load_state("networkidle", timeout=12000)
            except Exception:
                pass
            page.wait_for_timeout(1200)
            body = page.locator("body").inner_text(timeout=15000)

            # Exige que o número consultado apareça como número de CA no resultado.
            exact_ca = re.search(r"(?:N[ºo.]?\s*)?CA\s*[:#-]?\s*" + re.escape(ca) + r"\b", body, re.I)
            if not exact_ca and not re.search(r"\b" + re.escape(ca) + r"\b", body):
                return f"CA {ca}: não localizado no portal oficial."

            validity = re.search(r"Validade\s*:?\s*(\d{2}/\d{2}/\d{4})", body, re.I)
            if validity:
                try:
                    date_value = datetime.strptime(validity.group(1), "%d/%m/%Y").date()
                    status = "VENCIDO" if date_value < datetime.now().date() else "DENTRO DA VALIDADE"
                except ValueError:
                    status = "CONSULTADO — confira a validade no certificado"
            elif re.search(r"VENCID[OA]", body, re.I):
                status = "VENCIDO"
            else:
                status = "CONSULTADO — validade não identificada"

            # O CAEPI exibe primeiro uma grade; é necessário abrir o detalhe do registro.
            detail = page.locator(
                "img[title*='Detalhar' i], input[title*='Detalhar' i], "
                "a[title*='Detalhar' i], [alt*='Detalhar' i]"
            )
            if not detail.count():
                detail = page.get_by_text(re.compile(r"^Detalhar$", re.I))
            if detail.count():
                detail.first.click()
                try:
                    page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
                page.wait_for_timeout(900)

            # Na tela de detalhe, o certificado é aberto pelo botão Visualizar CA.
            visual = page.locator(
                "input[value*='Visualizar CA' i], button:has-text('Visualizar CA'), "
                "a:has-text('Visualizar CA'), [title*='Visualizar CA' i]"
            )
            if not visual.count():
                visual = page.get_by_text(re.compile(r"Visualizar\\s+CA", re.I))
            if not visual.count():
                return f"CA {ca}: {status}. Abri o resultado, mas o botão Visualizar CA não apareceu."

            cert_page = None
            try:
                with page.expect_popup(timeout=7000) as popup_info:
                    visual.first.click()
                cert_page = popup_info.value
            except Exception:
                visual.first.click()
                cert_page = page

            cert_page.wait_for_load_state("domcontentloaded", timeout=30000)
            cert_page.wait_for_timeout(700)
            temp_path = pdf_path.with_suffix(".tmp.pdf")
            cert_page.pdf(path=str(temp_path), format="A4", print_background=True)
            if not temp_path.exists() or temp_path.stat().st_size < 3000:
                if temp_path.exists():
                    temp_path.unlink()
                raise RuntimeError("O portal abriu o relatório, mas o PDF gerado ficou vazio ou incompleto.")
            temp_path.replace(pdf_path)
            if cert_page is not page:
                cert_page.close()
            return f"CA {ca}: {status} — PDF salvo em {pdf_path}"
        finally:
            context.close()
            browser.close()

class App:
    def __init__(self, root):
        self.root = root
        self.messages = queue.Queue()
        root.title("CertiFácil — Consulta de CA")
        root.geometry("820x600")
        root.minsize(680, 500)

        ttk.Label(root, text="CertiFácil", font=("Segoe UI", 21, "bold")).pack(anchor="w", padx=18, pady=(15, 0))
        ttk.Label(root, text="Consulta vários Certificados de Aprovação no portal oficial do Ministério do Trabalho.").pack(anchor="w", padx=18, pady=(0, 12))
        ttk.Label(root, text="Digite ou cole os números de CA (um por linha, espaço ou vírgula):").pack(anchor="w", padx=18)
        self.input = tk.Text(root, height=7, font=("Consolas", 11), wrap="word")
        self.input.pack(fill="x", padx=18, pady=6)

        controls = ttk.Frame(root)
        controls.pack(fill="x", padx=18, pady=5)
        self.btn = ttk.Button(controls, text="Consultar e salvar certificados", command=self.start)
        self.btn.pack(side="left")
        ttk.Button(controls, text="Abrir pasta dos PDFs", command=self.open_folder).pack(side="left", padx=8)
        self.force_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(controls, text="Atualizar PDFs que já existem", variable=self.force_var).pack(side="left", padx=8)

        self.path_label = ttk.Label(root, text=f"Destino: {OUT_DIR}")
        self.path_label.pack(anchor="w", padx=18, pady=5)
        ttk.Label(root, text="Andamento e resultados:").pack(anchor="w", padx=18, pady=(8, 0))
        self.logbox = tk.Text(root, height=15, state="disabled", font=("Segoe UI", 9), wrap="word")
        self.logbox.pack(fill="both", expand=True, padx=18, pady=(4, 14))
        self.log("Pronto. O programa utilizará o Microsoft Edge instalado no computador.")
        self.root.after(150, self.process_messages)

    def log(self, message):
        self.messages.put(message)

    def process_messages(self):
        try:
            while True:
                message = self.messages.get_nowait()
                self.logbox.configure(state="normal")
                self.logbox.insert("end", message + "\n")
                self.logbox.see("end")
                self.logbox.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(150, self.process_messages)

    def open_folder(self):
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(str(OUT_DIR))

    def start(self):
        raw = self.input.get("1.0", "end")
        cas = list(dict.fromkeys(re.findall(r"\d+", raw)))
        if not cas:
            messagebox.showwarning("CertiFácil", "Digite pelo menos um número de CA.")
            return
        self.btn.configure(state="disabled")
        self.log(f"Iniciando consulta de {len(cas)} CA(s)...")
        threading.Thread(target=self.worker, args=(cas, self.force_var.get()), daemon=True).start()

    def worker(self, cas, force_update):
        try:
            for ca in cas:
                self.log(f"Consultando CA {ca}...")
                try:
                    result = query_ca(ca, force_update, self.log)
                except Exception as exc:
                    result = f"CA {ca}: ERRO — {exc}"
                self.log(result)
        finally:
            self.log("Processo concluído.")
            self.root.after(0, lambda: self.btn.configure(state="normal"))

if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
