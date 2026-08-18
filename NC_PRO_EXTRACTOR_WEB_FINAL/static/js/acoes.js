const tabelaPontos={
  Drop:{Vitória:3,Derrota:1},Lojinha:{Vitória:6,Derrota:3},
  Joalheria:{Vitória:8,Derrota:3},Banco:{Vitória:15,Derrota:7},
  Invasão:{Vitória:12,Derrota:5}
};
function agoraLocalInput(){
  const d=new Date(); d.setMinutes(d.getMinutes()-d.getTimezoneOffset());
  return d.toISOString().slice(0,16);
}
async function hashArquivo(file){
  const buf=await file.arrayBuffer();
  const hash=await crypto.subtle.digest("SHA-256",buf);
  return [...new Uint8Array(hash)].map(b=>b.toString(16).padStart(2,"0")).join("");
}
function atualizarPontos(){
  const tipo=document.querySelector("#tipoAcao").value;
  const res=document.querySelector("#resultado").value;
  document.querySelector("#pontosPreview").textContent=`Pontuação automática: +${tabelaPontos[tipo][res]} pontos`;
}
document.addEventListener("DOMContentLoaded",()=>{
  document.querySelector("#dataAcao").value=agoraLocalInput();
  document.querySelector("#tipoAcao").addEventListener("change",atualizarPontos);
  document.querySelector("#resultado").addEventListener("change",atualizarPontos);
  atualizarPontos();

  document.querySelector("#formAcao").addEventListener("submit",async e=>{
    e.preventDefault();
    const status=document.querySelector("#statusAcao");
    const file=document.querySelector("#provaAcao").files[0];
    if(!file){status.innerHTML='<p class="bad">Selecione o print final.</p>';return}
    status.innerHTML='<p class="muted">Validando e salvando...</p>';
    try{
      const body={
        tipo:document.querySelector("#tipoAcao").value,
        data_hora:document.querySelector("#dataAcao").value,
        participantes:document.querySelector("#participantes").value,
        responsavel:document.querySelector("#responsavel").value,
        resumo:document.querySelector("#resumo").value,
        resultado:document.querySelector("#resultado").value,
        lucro:document.querySelector("#lucro").value || "Nada",
        prova_hash:await hashArquivo(file),
        prova_nome:file.name
      };
      const r=await fetch("/acoes/salvar",{method:"POST",headers:{"Content-Type":"application/json","Accept":"application/json"},body:JSON.stringify(body)});
      const j=await r.json();
      if(!r.ok||!j.sucesso) throw new Error(j.erro||"Não foi possível salvar.");
      status.innerHTML=`<p class="good">✅ Ação salva. +${j.pontos} pontos.</p>`;
      setTimeout(()=>location.reload(),900);
    }catch(err){status.innerHTML=`<p class="bad">❌ ${err.message}</p>`}
  });
});