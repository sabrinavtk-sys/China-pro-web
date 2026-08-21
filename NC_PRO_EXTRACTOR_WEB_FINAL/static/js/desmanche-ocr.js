(() => {
"use strict";

/*
  CHINA PRO — OCR DESMANCHE v2
  Calibrado para o layout real do Nova Capital:
  - Balão verde superior esquerdo:
      "Você recebeu R$60000 de amstel Hazard #830."
  - Menu do veículo centro/direita:
      "Huracan STO"
      "Veículo"
*/

function normalizar(t){
  return String(t||"")
    .replace(/\r/g,"\n")
    .replace(/[ \t]+/g," ")
    .replace(/\n{2,}/g,"\n")
    .trim();
}

function numero(v){
  const s=String(v||"")
    .replace(/[Oo]/g,"0")
    .replace(/[Il|]/g,"1")
    .replace(/[^\d]/g,"");
  const n=Number(s);
  return Number.isFinite(n)?n:0;
}

function extrairValor(texto){
  const t=normalizar(texto);
  const regras=[
    /voc[eê]\s+recebeu\s+R\s*\$?\s*([\dOoIl|., ]{3,18})(?=\s+(?:de|do|da)\b)/i,
    /recebeu\s+R\s*\$?\s*([\dOoIl|., ]{3,18})(?=\s+(?:de|do|da)\b)/i,
    /R\s*\$\s*([\dOoIl|., ]{3,18})(?=\s+(?:de|do|da|\n|$))/i
  ];
  for(const re of regras){
    const m=t.match(re);
    if(m){
      const n=numero(m[1]);
      if(n>=1000 && n<=999999999) return n;
    }
  }
  return 0;
}

function limparModelo(v){
  return String(v||"")
    .replace(/^[^A-Za-z0-9À-ÿ]+/,"")
    .replace(/[^A-Za-z0-9À-ÿ._ -]+$/,"")
    .replace(/\s{2,}/g," ")
    .trim()
    .slice(0,60);
}

function extrairModelo(texto){
  const t=normalizar(texto);

  // Regra principal: o modelo fica IMEDIATAMENTE acima da palavra "Veículo".
  const linhas=t.split("\n").map(x=>x.trim()).filter(Boolean);
  for(let i=1;i<linhas.length;i++){
    if(/^ve[ií]culo\b/i.test(linhas[i])){
      const modelo=limparModelo(linhas[i-1]);
      if(modelo.length>=2 && !/^(chaves|abrir|colocar)$/i.test(modelo)){
        return modelo;
      }
    }
  }

  // Fallback quando o Tesseract junta as duas linhas.
  const m=t.match(/([A-Za-z0-9À-ÿ._-]+(?:\s+[A-Za-z0-9À-ÿ._-]+){0,3})\s+ve[ií]culo\b/i);
  return m ? limparModelo(m[1]) : "";
}

function extrairDataHora(texto){
  const m=normalizar(texto).match(
    /(\d{1,2})[\/.-](\d{1,2})[\/.-](\d{4})\D{0,14}(\d{1,2})[:h](\d{2})/i
  );
  if(!m) return "";
  return `${m[3]}-${String(m[2]).padStart(2,"0")}-${String(m[1]).padStart(2,"0")}T${String(m[4]).padStart(2,"0")}:${String(m[5]).padStart(2,"0")}`;
}

function parsear(texto){
  const t=normalizar(texto);
  return {
    modelo:extrairModelo(t),
    quantidade:extrairValor(t),
    data_hora:extrairDataHora(t),
    texto:t
  };
}

function recortar(file, area, escala=3){
  return new Promise((resolve,reject)=>{
    const img=new Image();
    const url=URL.createObjectURL(file);
    img.onload=()=>{
      try{
        const sx=Math.round(img.naturalWidth*area.x);
        const sy=Math.round(img.naturalHeight*area.y);
        const sw=Math.round(img.naturalWidth*area.w);
        const sh=Math.round(img.naturalHeight*area.h);
        const c=document.createElement("canvas");
        c.width=Math.max(1,Math.round(sw*escala));
        c.height=Math.max(1,Math.round(sh*escala));
        const ctx=c.getContext("2d");
        ctx.imageSmoothingEnabled=true;
        ctx.drawImage(img,sx,sy,sw,sh,0,0,c.width,c.height);
        URL.revokeObjectURL(url);
        resolve(c);
      }catch(e){URL.revokeObjectURL(url);reject(e);}
    };
    img.onerror=()=>{URL.revokeObjectURL(url);reject(new Error("Não foi possível abrir o print."));};
    img.src=url;
  });
}

async function reconhecer(alvo, psm="6", onProgress){
  const r=await Tesseract.recognize(alvo,"por",{
    logger:m=>{
      if(onProgress && m.status==="recognizing text"){
        onProgress(Math.round((m.progress||0)*100));
      }
    }
  });
  return {
    texto:normalizar(r?.data?.text||""),
    confianca:Math.round(r?.data?.confidence||0)
  };
}

async function ler(file,onProgress){
  if(!file) throw new Error("Selecione o print do desmanche.");
  if(!window.Tesseract) throw new Error("Biblioteca OCR não carregou.");

  /*
    Recortes relativos para 1600x900 e outras resoluções 16:9:
    verde: topo/esquerda
    veículo: menu central/direita
    rodapé: data/hora do HUD
  */
  const [verde,veiculo,rodape]=await Promise.all([
    recortar(file,{x:0.005,y:0.095,w:0.31,h:0.115},4.5),
    recortar(file,{x:0.53,y:0.37,w:0.25,h:0.115},4.0),
    recortar(file,{x:0.58,y:0.94,w:0.41,h:0.06},4.0)
  ]);

  if(onProgress) onProgress(10);

  const leituraVerde=await reconhecer(verde,"6",p=>onProgress?.(10+Math.round(p*.30)));
  const leituraVeiculo=await reconhecer(veiculo,"6",p=>onProgress?.(40+Math.round(p*.30)));
  const leituraRodape=await reconhecer(rodape,"7",p=>onProgress?.(70+Math.round(p*.30)));

  const quantidade=extrairValor(leituraVerde.texto);
  const modelo=extrairModelo(leituraVeiculo.texto);
  const data_hora=extrairDataHora(leituraRodape.texto);

  const confiancas=[
    quantidade ? leituraVerde.confianca : 0,
    modelo ? leituraVeiculo.confianca : 0,
    data_hora ? leituraRodape.confianca : 0
  ].filter(v=>v>0);

  const confianca=confiancas.length
    ? Math.round(confiancas.reduce((a,b)=>a+b,0)/confiancas.length)
    : 0;

  const resultado={
    modelo,
    quantidade,
    data_hora,
    confianca,
    leituras:{
      balaoVerde:leituraVerde.texto,
      veiculo:leituraVeiculo.texto,
      rodape:leituraRodape.texto
    }
  };

  console.log("OCR DESMANCHE v2:",resultado);
  return resultado;
}

window.DesmancheOCR={ler,parsear,extrairValor,extrairModelo,extrairDataHora};
})();