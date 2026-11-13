import os
import re
import sys
import threading
import queue
import asyncio
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

PORTAL_URL = "https://caepi.trabalho.gov.br/internet/ConsultaCAInternet.aspx"
APP_VERSION = "2026.11.13-r2"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


def safe_filename(value):
    return re.sub(r"[^0-9A-Za-z_-]+", "_", str(value)).strip("_") or "CA"


class CADownloaderFixed:
    def __init__(self):
        self.root = ctk.CTk()
        self.root.title("CertiFácil")
        self.root.geometry("900x700")
        self.root.minsize(600, 500)

        self.download_path = ctk.StringVar(value=str(Path.cwd() / "downloads"))
        self.ca_list = []
        self.is_downloading = False
        self.ui_queue = queue.Queue()

        self.setup_ui()
        self.process_ui_queue()

    def setup_ui(self):
        self.main_canvas = ctk.CTkScrollableFrame(self.root)
        self.main_canvas.pack(fill="both", expand=True, padx=10, pady=10)
        main = self.main_canvas

        ctk.CTkLabel(main, text="CertiFácil",
                     font=ctk.CTkFont(size=28, weight="bold")).pack(pady=(20, 10))
        ctk.CTkLabel(
            main,
            text="Praticidade e agilidade para baixar seus Certificados de Aprovação (CA)",
            font=ctk.CTkFont(size=14)
        ).pack(pady=(0, 20))

        ca_frame = ctk.CTkFrame(main)
        ca_frame.pack(fill="x", pady=(0, 20))
        ctk.CTkLabel(ca_frame, text="Números dos CAs:",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=20, pady=(20, 5))

        input_frame = ctk.CTkFrame(ca_frame)
        input_frame.pack(fill="x", padx=20, pady=(0, 10))
        self.ca_entry = ctk.CTkEntry(
            input_frame,
            placeholder_text="Digite o número do CA e pressione Enter",
            font=ctk.CTkFont(size=14), height=40
        )
        self.ca_entry.pack(side="left", fill="x", expand=True, padx=(10, 5), pady=10)
        self.ca_entry.bind("<Return>", self.add_ca)
        ctk.CTkButton(input_frame, text="Adicionar", command=self.add_ca,
                      width=100, height=40).pack(side="right", padx=(5, 10), pady=10)

        list_frame = ctk.CTkFrame(ca_frame)
        list_frame.pack(fill="x", padx=20, pady=(0, 15))
        ctk.CTkLabel(list_frame, text="CAs na lista:",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=10, pady=(10, 5))
        self.ca_list_frame = ctk.CTkFrame(list_frame, fg_color="transparent")
        self.ca_list_frame.pack(fill="x", padx=10, pady=(0, 5))
        ctk.CTkButton(
            list_frame, text="Limpar Lista", command=self.clear_ca_list,
            fg_color="transparent", border_width=2, text_color=("gray10", "#DCE4EE"),
            width=120, height=30
        ).pack(anchor="e", padx=10, pady=(5, 10))

        path_frame = ctk.CTkFrame(main)
        path_frame.pack(fill="x", pady=(0, 20))
        ctk.CTkLabel(path_frame, text="Pasta de Download:",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=20, pady=(15, 5))
        path_input_frame = ctk.CTkFrame(path_frame)
        path_input_frame.pack(fill="x", padx=20, pady=(0, 15))
        self.path_entry = ctk.CTkEntry(path_input_frame, textvariable=self.download_path,
                                       font=ctk.CTkFont(size=12), height=35)
        self.path_entry.pack(side="left", fill="x", expand=True, padx=(10, 5), pady=10)
        ctk.CTkButton(path_input_frame, text="Procurar", command=self.select_download_path,
                      width=100, height=35).pack(side="right", padx=(5, 10), pady=10)

        self.start_button = ctk.CTkButton(
            main, text="Iniciar Downloads", command=self.start_downloads,
            font=ctk.CTkFont(size=16, weight="bold"), height=50,
            fg_color="#1f538d", hover_color="#14375e"
        )
        self.start_button.pack(fill="x", padx=20, pady=(0, 10))

        self.progress_bar = ctk.CTkProgressBar(main, height=12)
        self.progress_bar.pack(fill="x", padx=20, pady=(0, 15))
        self.progress_bar.set(0)

        status_frame = ctk.CTkFrame(main)
        status_frame.pack(fill="both", expand=True, pady=(0, 10))
        ctk.CTkLabel(status_frame, text="Status:",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=15, pady=(10, 5))
        self.status_text = ctk.CTkTextbox(status_frame, height=150, font=ctk.CTkFont(size=11))
        self.status_text.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.log_status(f"CertiFácil {APP_VERSION} pronto. Adicione um ou mais números de CA.")

    def process_ui_queue(self):
        try:
            while True:
                kind, value = self.ui_queue.get_nowait()
                if kind == "log":
                    self.status_text.insert("end", value + "\n")
                    self.status_text.see("end")
                elif kind == "progress":
                    self.progress_bar.set(value)
                elif kind == "done":
                    self.is_downloading = False
                    self.start_button.configure(state="normal")
        except queue.Empty:
            pass
        self.root.after(100, self.process_ui_queue)

    def log_status(self, message):
        self.ui_queue.put(("log", str(message)))

    def add_ca(self, event=None):
        value = re.sub(r"\D", "", self.ca_entry.get().strip())
        if not value:
            return
        if value in self.ca_list:
            self.log_status(f"CA {value} já está na lista.")
        else:
            self.ca_list.append(value)
            self.update_ca_list_display()
            self.log_status(f"CA {value} adicionado à lista.")
        self.ca_entry.delete(0, "end")

    def update_ca_list_display(self):
        for child in self.ca_list_frame.winfo_children():
            child.destroy()
        for ca in self.ca_list:
            item = ctk.CTkFrame(self.ca_list_frame)
            item.pack(fill="x", pady=2)
            ctk.CTkLabel(item, text=f"CA {ca}", anchor="w",
                         font=ctk.CTkFont(size=13)).pack(side="left", padx=10, pady=5)
            ctk.CTkButton(item, text="Remover", width=80, height=26,
                          fg_color="#8b3030", hover_color="#6d2424",
                          command=lambda n=ca: self.remove_ca(n)).pack(side="right", padx=8, pady=4)

    def remove_ca(self, ca):
        if ca in self.ca_list:
            self.ca_list.remove(ca)
            self.update_ca_list_display()

    def clear_ca_list(self):
        self.ca_list.clear()
        self.update_ca_list_display()

    def select_download_path(self):
        selected = filedialog.askdirectory()
        if selected:
            self.download_path.set(selected)

    def start_downloads(self):
        if self.is_downloading:
            return
        if not self.ca_list:
            messagebox.showwarning("CertiFácil", "Adicione pelo menos um número de CA à lista.")
            return
        folder = self.download_path.get().strip()
        if not folder:
            messagebox.showwarning("CertiFácil", "Selecione a pasta de download.")
            return
        self.is_downloading = True
        self.start_button.configure(state="disabled")
        self.progress_bar.set(0)
        cas = list(self.ca_list)
        threading.Thread(target=self.run_downloads, args=(cas, folder), daemon=True).start()

    def run_downloads(self, cas, folder):
        try:
            os.makedirs(folder, exist_ok=True)
            with sync_playwright() as p:
                browser = self.launch_browser(p)
                context = browser.new_context(accept_downloads=True)
                try:
                    for index, ca in enumerate(cas, 1):
                        try:
                            self.baixar_ca_individual(context, ca, folder)
                        except Exception as exc:
                            self.log_status(f"❌ CA {ca}: {exc}")
                        self.ui_queue.put(("progress", index / len(cas)))
                finally:
                    context.close()
                    browser.close()
            self.log_status("Processo concluído.")
        except Exception as exc:
            self.log_status(f"Erro geral: {exc}")
        finally:
            self.ui_queue.put(("done", None))

    def launch_browser(self, playwright):
        # Usa o Edge instalado no Windows, sem exigir instalação separada do Python.
        try:
            return playwright.chromium.launch(channel="msedge", headless=True)
        except Exception as exc:
            raise RuntimeError(
                "Não foi possível iniciar o Microsoft Edge. Confirme que ele está instalado. "
                f"Detalhe: {exc}"
            )

    def _first_visible(self, page, selectors):
        for selector in selectors:
            loc = page.locator(selector)
            try:
                if loc.count() and loc.first.is_visible():
                    return loc.first
            except Exception:
                continue
        return None

    def baixar_ca_individual(self, context, ca_numero, download_path):
        self.log_status(f"Iniciando processo para o CA: {ca_numero}")
        page = context.new_page()
        try:
            page.goto(PORTAL_URL, wait_until="domcontentloaded", timeout=60000)

            # Seletores confirmados na página oficial em 13/11/2026.
            # ASP.NET WebForms usa "_" no id renderizado e "$" no atributo name.
            campo = None
            for selector in (
                "#ctl00_PlaceHolderConteudo_txtNumeroCA",
                'input[name="ctl00$PlaceHolderConteudo$txtNumeroCA"]',
                'input[id$="txtNumeroCA"]',
                'input[name$="txtNumeroCA"]',
            ):
                candidate = page.locator(selector)
                try:
                    candidate.first.wait_for(state="visible", timeout=8000)
                    if candidate.count() > 0 and candidate.first.is_visible():
                        campo = candidate.first
                        break
                except PlaywrightTimeoutError:
                    continue

            # Último fallback: o formulário oficial possui um único campo de texto para o CA.
            if campo is None:
                text_inputs = page.locator('form input[type="text"]:visible')
                if text_inputs.count() == 1:
                    campo = text_inputs.first

            if campo is None:
                inputs = page.locator("form input").evaluate_all(
                    "(els) => els.map(e => ({type:e.type,id:e.id,name:e.name,value:e.value}))"
                )
                raise RuntimeError(
                    "Não localizei o campo Nº do CA na página oficial. "
                    f"URL: {page.url}. Campos encontrados: {inputs}"
                )

            campo.fill(str(ca_numero))
            if (campo.input_value() or "").strip() != str(ca_numero):
                raise RuntimeError("O número do CA não permaneceu preenchido no formulário.")

            # Botão oficial confirmado: input type=button com id fixo.
            consultar = page.locator("#ctl00_PlaceHolderConteudo_btnConsultar")
            if consultar.count() == 0:
                consultar = page.locator(
                    'input[name="ctl00$PlaceHolderConteudo$btnConsultar"], '
                    'input[type="button"][value="Consultar"]'
                )
            if consultar.count() == 0:
                raise RuntimeError("Campo preenchido, mas o botão oficial Consultar não foi localizado.")
            consultar.first.click()
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except PlaywrightTimeoutError:
                pass
            page.wait_for_timeout(900)

            body = page.locator("body").inner_text(timeout=15000)
            if re.search(r"nenhum CA cadastrado|não foi encontrado|nao foi encontrado|nenhum registro", body, re.I):
                self.log_status(f"CA {ca_numero} não encontrado no cadastro oficial.")
                return

            detalhe = self._first_visible(page, [
                '#PlaceHolderConteudo_grdListaResultado_btnDetalhar_0',
                'input[id*="grdListaResultado"][id*="btnDetalhar"]',
                'a[id*="grdListaResultado"][id*="Detalhar"]',
                'input[title*="Detalhar"]',
                'img[alt*="Detalhar"]',
                'a[title*="Detalhar"]'
            ])
            if detalhe is None:
                # Procura controles de detalhe pelo texto/atributos no resultado atual.
                detalhe = self._first_visible(page, [
                    'input[value*="Detalhar"]',
                    'button:has-text("Detalhar")',
                    'a:has-text("Detalhar")'
                ])
            if detalhe is None:
                # Um resultado pode existir sem ação de detalhe; não gerar PDF de uma página errada.
                raise RuntimeError("A consulta foi enviada, mas não apareceu um resultado com a ação Detalhar. "
                                   "Confira se o CA existe no portal.")
            detalhe.click()
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except PlaywrightTimeoutError:
                pass
            page.wait_for_timeout(700)

            validade = ""
            for selector in [
                '#PlaceHolderConteudo_lblDTValidade',
                '[id$="lblDTValidade"]',
                'span[id*="DTValidade"]'
            ]:
                try:
                    if page.locator(selector).count():
                        validade = page.locator(selector).first.inner_text().strip()
                        break
                except Exception:
                    pass
            status = ""
            match = re.search(r"\d{2}/\d{2}/\d{4}", validade)
            if match:
                try:
                    data = datetime.strptime(match.group(), "%d/%m/%Y").date()
                    status = " (Vencido)" if data < datetime.now().date() else " (Vigente)"
                except ValueError:
                    pass
            self.log_status(f"CA {ca_numero} encontrado{status}.")

            visualizar = self._first_visible(page, [
                'input[name="ctl00$PlaceHolderConteudo$btnVisualizarCA"]',
                'input[id$="_btnVisualizarCA"]',
                '#PlaceHolderConteudo_btnVisualizarCA',
                'input[value*="Visualizar CA"]',
                'button:has-text("Visualizar CA")',
                'a:has-text("Visualizar CA")'
            ])
            if visualizar is None:
                raise RuntimeError("O detalhe foi aberto, mas o botão Visualizar CA não apareceu.")

            pdf_path = Path(download_path) / f"CA_{safe_filename(ca_numero)}{status.replace(' ', '')}.pdf"
            if pdf_path.exists():
                pdf_path = Path(download_path) / f"CA_{safe_filename(ca_numero)}_{datetime.now():%Y%m%d_%H%M%S}.pdf"

            cert_page = None
            response = None
            try:
                with page.expect_popup(timeout=8000) as popup_info:
                    visualizar.click()
                cert_page = popup_info.value
            except PlaywrightTimeoutError:
                # O clique pode ter navegado na própria aba, sem abrir popup.
                cert_page = page

            if cert_page is None:
                cert_page = page
            try:
                cert_page.wait_for_load_state("domcontentloaded", timeout=20000)
            except PlaywrightTimeoutError:
                pass
            cert_page.wait_for_timeout(1500)

            # Se o portal responder diretamente com application/pdf, salva o corpo original.
            if response is not None:
                try:
                    if "application/pdf" in response.headers.get("content-type", "").lower():
                        data = response.body()
                        if data.startswith(b"%PDF") and len(data) > 2000:
                            pdf_path.write_bytes(data)
                            self.log_status(f"✅ CA {ca_numero} baixado com sucesso ({pdf_path.stat().st_size / 1024:.2f} KB).")
                            return
                except Exception:
                    pass

            # A página de impressão do CAEPI é HTML; imprime a visualização para PDF.
            cert_page.pdf(path=str(pdf_path), format="A4", print_background=True)
            if not pdf_path.exists() or pdf_path.stat().st_size < 2000:
                if pdf_path.exists():
                    pdf_path.unlink()
                raise RuntimeError("O arquivo PDF ficou vazio ou incompleto.")
            self.log_status(f"✅ CA {ca_numero} baixado com sucesso ({pdf_path.stat().st_size / 1024:.2f} KB).")
        finally:
            try:
                page.close()
            except Exception:
                pass

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    app = CADownloaderFixed()
    app.run()
