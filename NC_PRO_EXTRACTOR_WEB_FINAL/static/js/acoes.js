const tabelaPontos={
  Drop:{Vitória:3,Derrota:1},
  Lojinha:{Vitória:6,Derrota:3},
  Joalheria:{Vitória:8,Derrota:3},
  Banco:{Vitória:15,Derrota:7},
  Invasão:{Vitória:12,Derrota:5}
};

function agoraLocalInput(){
  const d=new Date();
  d.setMinutes(d.getMinutes()-d.getTimezoneOffset());
  return d.toISOString().slice(0,16);
}

async function hashArquivo(file){
  const buf=await file.arrayBuffer();
  const hash=await crypto.subtle.digest("SHA-256",buf);
  return [...new Uint8Array(hash)].map(b=>b.toString(16).padStart(2,"0")).join("");
}

function atualizarPontos(){
  const tipo=document.querySelector("#tipoAcao")?.value;
  const res=document.querySelector("#resultado")?.value;
  const preview=document.querySelector("#pontosPreview");
  const pontos=tabelaPontos?.[tipo]?.[res];
  if(preview) preview.textContent=`Pontuação automática: +${pontos ?? 0} pontos`;
}

async function lerRespostaAPI(resposta){
  const contentType=(resposta.headers.get("content-type")||"").toLowerCase();
  const texto=await resposta.text();

  if(contentType.includes("application/json")){
    try{return JSON.parse(texto)}
    catch{throw new Error(`Resposta JSON inválida do servidor (HTTP ${resposta.status}).`)}
  }

  if(resposta.redirected || resposta.url.includes("/login")){
    throw new Error("Sua sessão expirou. Entre novamente no sistema.");
  }

  throw new Error(`O servidor respondeu em formato incorreto (HTTP ${resposta.status}).`);
}

document.addEventListener("DOMContentLoaded",()=>{
  const data=document.querySelector("#dataAcao");
  const tipo=document.querySelector("#tipoAcao");
  const resultado=document.querySelector("#resultado");
  const form=document.querySelector("#formAcao");

  if(data && !data.value) data.value=agoraLocalInput();
  tipo?.addEventListener("change",atualizarPontos);
  resultado?.addEventListener("change",atualizarPontos);
  atualizarPontos();


  const limparAcao=document.querySelector("#limparAcao");

  function limparFormularioAcao(){
    form?.reset();

    if(data){
      data.value=agoraLocalInput();
    }

    const status=document.querySelector("#statusAcao");
    if(status){
      status.innerHTML="";
    }

    atualizarPontos();

    console.log("FORMULÁRIO DE AÇÃO LIMPO");
  }

  limparAcao?.addEventListener("click",()=>{
    if(confirm("Limpar os dados desta ação e começar novamente?")){
      limparFormularioAcao();
    }
  });

  if(!form) return;

  form.addEventListener("submit",async e=>{
    e.preventDefault();
    const status=document.querySelector("#statusAcao");
    const inputArquivo=document.querySelector("#provaAcao");
    const file=inputArquivo?.files?.[0];
    const botao=form.querySelector('button[type="submit"]');

    if(!file){
      if(status) status.innerHTML='<p class="bad">❌ Selecione o print final obrigatório.</p>';
      return;
    }

    if(botao) botao.disabled=true;
    if(status) status.innerHTML='<p class="muted">Validando e salvando...</p>';

    try{
      const body={
        tipo:tipo?.value||"",
        data_hora:data?.value||"",
        participantes:document.querySelector("#participantes")?.value||"",
        responsavel:document.querySelector("#responsavel")?.value||"",
        resumo:document.querySelector("#resumo")?.value||"",
        resultado:resultado?.value||"",
        lucro:document.querySelector("#lucro")?.value||"Nada",
        prova_hash:await hashArquivo(file),
        prova_nome:file.name
      };

      const resposta=await fetch("/acoes/salvar",{
        method:"POST",
        credentials:"same-origin",
        headers:{
          "Content-Type":"application/json",
          "Accept":"application/json",
          "X-Requested-With":"XMLHttpRequest"
        },
        body:JSON.stringify(body)
      });

      const dados=await lerRespostaAPI(resposta);
      if(!resposta.ok || !dados.sucesso){
        throw new Error(dados.erro || `Não foi possível salvar (HTTP ${resposta.status}).`);
      }

      if(status) status.innerHTML=`<p class="good">✅ Ação salva com sucesso. +${dados.pontos} pontos.</p>`;
      form.reset();
      if(data) data.value=agoraLocalInput();
      atualizarPontos();
      setTimeout(()=>location.reload(),700);

    }catch(err){
      console.error("ERRO AO SALVAR AÇÃO:",err);
      const msg=String(err.message||"Não foi possível salvar.").replace(/[<>]/g,"");
      if(status) status.innerHTML=`<p class="bad">❌ ${msg}</p>`;
    }finally{
      if(botao) botao.disabled=false;
    }
  });
});
