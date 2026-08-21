function agoraLocalInput(){
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0,16);
}

async function hashArquivo(file){
  const buf = await file.arrayBuffer();
  const hash = await crypto.subtle.digest("SHA-256", buf);
  return [...new Uint8Array(hash)]
    .map(b => b.toString(16).padStart(2,"0"))
    .join("");
}

async function lerRespostaAPI(resposta){
  const contentType = (resposta.headers.get("content-type") || "").toLowerCase();
  const texto = await resposta.text();

  if(contentType.includes("application/json")){
    try{
      return JSON.parse(texto);
    }catch{
      throw new Error(`Resposta JSON inválida do servidor (HTTP ${resposta.status}).`);
    }
  }

  // Não expõe HTML da Vercel na tela.
  // Mostra status suficiente para identificar o problema.
  const erro = new Error(
    `O servidor respondeu em formato incorreto (HTTP ${resposta.status}).`
  );
  erro.httpStatus = resposta.status;
  throw erro;
}

document.addEventListener("DOMContentLoaded", () => {
  const data = document.querySelector("#dataDesmanche");
  const form = document.querySelector("#formDesmanche");
  const arquivoOCR = document.querySelector("#provaDesmanche");
  const botaoOCR = document.querySelector("#btnOcrDesmanche");
  const infoOCR = document.querySelector("#ocrDesmancheInfo");

  async function processarOCRDesmanche(){
    const file=arquivoOCR?.files?.[0];
    if(!file){if(infoOCR)infoOCR.textContent="Selecione o print primeiro.";return;}
    if(botaoOCR)botaoOCR.disabled=true;
    try{
      const r=await window.DesmancheOCR.ler(file,p=>{if(infoOCR)infoOCR.textContent=`Lendo print... ${p}%`;});
      const modelo=document.querySelector("#modelo");
      const quantidade=document.querySelector("#quantidade");
      if(r.modelo&&modelo)modelo.value=r.modelo;
      if(r.quantidade&&quantidade)quantidade.value=r.quantidade;
      if(r.data_hora&&data)data.value=r.data_hora;
      const achados=[r.modelo&&"modelo",r.quantidade&&"valor",r.data_hora&&"data/hora"].filter(Boolean);
      if(infoOCR)infoOCR.textContent=achados.length?`✅ OCR concluído (${r.confianca}%): ${achados.join(", ")}. Confira antes de salvar.`:"⚠️ Não consegui identificar os campos. Preencha manualmente.";
      console.log("OCR DESMANCHE:",r);
    }catch(err){
      console.error("ERRO OCR DESMANCHE:",err);
      if(infoOCR)infoOCR.textContent=`❌ ${err.message||"Falha ao ler o print."}`;
    }finally{if(botaoOCR)botaoOCR.disabled=false;}
  }
  botaoOCR?.addEventListener("click",processarOCRDesmanche);
  arquivoOCR?.addEventListener("change",processarOCRDesmanche);

  if(data && !data.value){
    data.value = agoraLocalInput();
  }

  if(!form) return;

  form.addEventListener("submit", async (e) => {
    e.preventDefault();

    const status = document.querySelector("#statusDesmanche");
    const inputArquivo = document.querySelector("#provaDesmanche");
    const file = inputArquivo?.files?.[0];

    if(!file){
      status.innerHTML = '<p class="bad">❌ Selecione o print obrigatório.</p>';
      return;
    }

    const botao = form.querySelector('button[type="submit"]');
    if(botao) botao.disabled = true;

    status.innerHTML = '<p class="muted">Validando e salvando...</p>';

    try{
      const body = {
        modelo: document.querySelector("#modelo").value.trim(),
        data_hora: document.querySelector("#dataDesmanche").value,
        quantidade: document.querySelector("#quantidade").value,
        destino_pontos: document.querySelector("#destino").value,
        prova_hash: await hashArquivo(file),
        prova_nome: file.name
      };

      const resposta = await fetch("/desmanches/salvar", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "Accept": "application/json",
          "X-Requested-With": "XMLHttpRequest"
        },
        body: JSON.stringify(body)
      });

      const dados = await lerRespostaAPI(resposta);

      if(!resposta.ok || !dados.sucesso){
        const mensagem = dados.erro || `Não foi possível salvar (HTTP ${resposta.status}).`;
        const erro = new Error(mensagem);
        erro.codigo = dados.codigo;
        throw erro;
      }

      status.innerHTML =
        `<p class="good">✅ Desmanche salvo com sucesso. +${dados.pontos} pontos.</p>`;

      form.reset();
      if(data) data.value = agoraLocalInput();

      setTimeout(() => location.reload(), 700);

    }catch(err){
      console.error("ERRO AO SALVAR DESMANCHE:", err);

      status.innerHTML =
        `<p class="bad">❌ ${String(err.message || "Não foi possível salvar.").replace(/[<>]/g,"")}</p>`;
    }finally{
      if(botao) botao.disabled = false;
    }
  });
});
