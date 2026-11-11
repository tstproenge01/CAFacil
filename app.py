import os, re, sys, threading, subprocess
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

PORTAL = "https://caepi.trabalho.gov.br/internet/ConsultaCAInternet.aspx"
APP_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "CAFacil"
BROWSER_DIR = APP_DIR / "ms-playwright"
OUT_DIR = Path.home() / "Documents" / "Certificados CA"

def ensure_browser(log):
    APP_DIR.mkdir(parents=True, exist_ok=True)
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(BROWSER_DIR)
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            try:
                b = p.chromium.launch(headless=True)
                b.close()
                return
            except Exception:
                log("Preparando o navegador na primeira execução (pode demorar)...")
        from playwright._impl._driver import compute_driver_executable
        driver, cli = compute_driver_executable()
        result = subprocess.run([str(driver), str(cli), "install", "chromium"], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError((result.stderr or result.stdout or "Falha ao instalar navegador")[-1800:])
    except Exception as e:
        raise RuntimeError("Não foi possível preparar o navegador. Verifique a internet e tente novamente.\n" + str(e))

def safe_name(s):
    return re.sub(r"[^0-9A-Za-z_-]+", "_", s).strip("_") or "CA"

def run_query(ca, log):
    from playwright.sync_api import sync_playwright
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pdf = OUT_DIR / f"CA_{safe_name(ca)}.pdf"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(PORTAL, wait_until="domcontentloaded", timeout=60000)
            # O portal oficial apresenta o campo Nº do CA e o botão Consultar.
            fields = page.locator("input[type='text']")
            if fields.count() == 0:
                raise RuntimeError("O portal mudou: campo de consulta não localizado.")
            fields.first.fill(ca)
            buttons = page.get_by_role("button", name=re.compile("Consultar", re.I))
            if buttons.count():
                buttons.first.click()
            else:
                page.get_by_text(re.compile(r"^Consultar$", re.I)).first.click()
            page.wait_for_load_state("domcontentloaded", timeout=30000)
            page.wait_for_timeout(1200)
            body = page.locator("body").inner_text()
            if not re.search(r"\bCA\b", body, re.I) or ca not in body:
                return f"CA {ca}: não localizado ou portal sem resultado."
            status = "VENCIDO" if re.search(r"VENCID[OA]", body, re.I) else ("ATIVO" if re.search(r"VALID[OA]", body, re.I) else "CONSULTADO")
            if pdf.exists():
                log(f"CA {ca}: PDF já existe; não baixei novamente.")
                return f"CA {ca}: {status} — PDF já salvo."
            link = page.get_by_text(re.compile("Visualizar CA", re.I))
            if not link.count():
                link = page.locator("a").filter(has_text=re.compile("Visualizar CA", re.I))
            if not link.count():
                return f"CA {ca}: {status} — resultado encontrado, mas botão Visualizar CA não localizado."
            try:
                with page.expect_popup(timeout=5000) as pop:
                    link.first.click()
                cert = pop.value
            except Exception:
                link.first.click()
                cert = page
            cert.wait_for_load_state("domcontentloaded", timeout=30000)
            cert.wait_for_timeout(800)
            cert.pdf(path=str(pdf), format="A4", print_background=True)
            if cert is not page:
                cert.close()
            return f"CA {ca}: {status} — PDF salvo em {pdf}"
        finally:
            browser.close()

class App:
    def __init__(self, root):
        self.root=root
        root.title("CA Fácil — Consulta de Certificados de Aprovação")
        root.geometry("760x540")
        root.minsize(650,450)
        ttk.Label(root,text="CA Fácil",font=("Segoe UI",20,"bold")).pack(anchor="w",padx=18,pady=(16,0))
        ttk.Label(root,text="Consulte vários números de CA no portal oficial do Ministério do Trabalho.").pack(anchor="w",padx=18,pady=(0,12))
        ttk.Label(root,text="Digite ou cole os números de CA (um por linha ou separados por vírgula):").pack(anchor="w",padx=18)
        self.input=tk.Text(root,height=6,font=("Consolas",11),wrap="word")
        self.input.pack(fill="x",padx=18,pady=6)
        row=ttk.Frame(root); row.pack(fill="x",padx=18,pady=4)
        self.btn=ttk.Button(row,text="Consultar e salvar PDFs",command=self.start); self.btn.pack(side="left")
        ttk.Button(row,text="Abrir pasta dos PDFs",command=self.open_folder).pack(side="left",padx=8)
        ttk.Label(root,text=f"Destino: {OUT_DIR}").pack(anchor="w",padx=18,pady=5)
        ttk.Label(root,text="Andamento:").pack(anchor="w",padx=18,pady=(8,0))
        self.logbox=tk.Text(root,height=12,state="disabled",font=("Segoe UI",9),wrap="word")
        self.logbox.pack(fill="both",expand=True,padx=18,pady=(4,14))
        self.log("Pronto. A primeira consulta prepara o navegador automaticamente.")
    def log(self,msg):
        self.logbox.configure(state="normal"); self.logbox.insert("end",msg+"\n"); self.logbox.see("end"); self.logbox.configure(state="disabled")
    def open_folder(self):
        OUT_DIR.mkdir(parents=True,exist_ok=True)
        os.startfile(str(OUT_DIR))
    def start(self):
        raw=self.input.get("1.0","end")
        cas=list(dict.fromkeys(re.findall(r"\d+",raw)))
        if not cas:
            messagebox.showwarning("CA Fácil","Digite pelo menos um número de CA."); return
        self.btn.configure(state="disabled")
        threading.Thread(target=self.worker,args=(cas,),daemon=True).start()
    def worker(self,cas):
        try:
            ensure_browser(lambda m:self.root.after(0,self.log,m))
            for ca in cas:
                self.root.after(0,self.log,f"Consultando CA {ca}...")
                try: result=run_query(ca,lambda m:self.root.after(0,self.log,m))
                except Exception as e: result=f"CA {ca}: erro — {e}"
                self.root.after(0,self.log,result)
        except Exception as e:
            self.root.after(0,self.log,str(e))
        finally:
            self.root.after(0,lambda:self.btn.configure(state="normal"))
            self.root.after(0,lambda:self.log("Processo concluído. Confira os resultados acima."))
if __name__=="__main__":
    root=tk.Tk()
    App(root)
    root.mainloop()
