function agoraLocalInput(){
  const d=new Date(); d.setMinutes(d.getMinutes()-d.getTimezoneOffset());
  return d.toISOString().slice(0,16);
}
async function hashArquivo(file){
  const buf=await file.arrayBuffer();
  const hash=await crypto.subtle.digest("SHA-256",buf);
  return [...new Uint8Array(hash)].map(b=>b.toString(16).padStart(2,"0")).join("");
}
document.addEventListener("DOMContentLoaded",()=>{
  document.querySelector("#dataDesmanche").value=agoraLocalInput();
  document.querySelector("#formDesmanche").addEventListener("submit",async e=>{
    e.preventDefault();
    const status=document.querySelector("#statusDesmanche");
    const file=document.querySelector("#provaDesmanche").files[0];
    if(!file){status.innerHTML='<p class="bad">Selecione o print obrigatório.</p>';return}
    status.innerHTML='<p class="muted">Validando e salvando...</p>';
    try{
      const body={
        modelo:document.querySelector("#modelo").value,
        data_hora:document.querySelector("#dataDesmanche").value,
        quantidade:document.querySelector("#quantidade").value,
        destino_pontos:document.querySelector("#destino").value,
        prova_hash:await hashArquivo(file),
        prova_nome:file.name
      };
      const r=await fetch("/desmanches/salvar",{method:"POST",headers:{"Content-Type":"application/json","Accept":"application/json"},body:JSON.stringify(body)});
      const j=await r.json();
      if(!r.ok||!j.sucesso) throw new Error(j.erro||"Não foi possível salvar.");
      status.innerHTML=`<p class="good">✅ Desmanche salvo. +${j.pontos} pontos.</p>`;
      setTimeout(()=>location.reload(),900);
    }catch(err){status.innerHTML=`<p class="bad">❌ ${err.message}</p>`}
  });
});