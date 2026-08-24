(() => {
"use strict";

const MIN_PERCENT = 20;
const MAX_PERCENT = 40;

function parseValorBR(valor){
  let texto = String(valor || "")
    .trim()
    .replace(/[^\d.,]/g, "");

  if(!texto){
    return 0;
  }

  /*
    Regras:
    1.000.000      -> 1000000
    1.000.000,50   -> 1000000.50
    1000000        -> 1000000
    1000000,50     -> 1000000.50
  */
  if(texto.includes(",")){
    const partes = texto.split(",");
    const inteiro = partes[0].replace(/\./g, "");
    const decimal = (partes[1] || "").replace(/\D/g, "").slice(0, 2);
    const normalizado = decimal ? `${inteiro}.${decimal}` : inteiro;
    const n = Number(normalizado);
    return Number.isFinite(n) ? n : 0;
  }

  // Sem vírgula, pontos são separadores de milhar.
  texto = texto.replace(/\./g, "");
  const n = Number(texto);
  return Number.isFinite(n) ? n : 0;
}

function formatarBRL(valor){
  return Number(valor || 0).toLocaleString(
    "pt-BR",
    {
      style: "currency",
      currency: "BRL",
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    }
  );
}

function formatarCampo(valor){
  const numero = parseValorBR(valor);

  if(!numero){
    return "";
  }

  // No input, usa formato inteiro enquanto o usuário digita.
  return Math.round(numero).toLocaleString("pt-BR");
}

function numeroPuro(valor){
  const numero = Number(valor || 0);

  if(Number.isInteger(numero)){
    return String(numero);
  }

  return numero
    .toFixed(2)
    .replace(".", ",");
}

async function copiarTexto(texto){
  if(navigator.clipboard?.writeText){
    await navigator.clipboard.writeText(texto);
    return;
  }

  const area = document.createElement("textarea");
  area.value = texto;
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  document.execCommand("copy");
  area.remove();
}


function extrairValorRecebidoOCR(texto){
  const bruto = String(texto || "")
    .replace(/\r/g, "\n")
    .replace(/[|]/g, "I");

  const normalizado = bruto
    .replace(/\s+/g, " ")
    .trim();

  const padroes = [
    /voc[eêé]\s+recebeu\s+(?:r\s*\$|rs|r\$)?\s*([\d][\d\s.,]{2,})/i,
    /recebeu\s+(?:r\s*\$|rs|r\$)?\s*([\d][\d\s.,]{2,})/i,
    /receb(?:eu|ido)\s+(?:r\s*\$|rs|r\$)?\s*([\d][\d\s.,]{2,})/i
  ];

  for(const padrao of padroes){
    const match = normalizado.match(padrao);

    if(!match){
      continue;
    }

    let numero = String(match[1] || "")
      .trim()
      .replace(/\s/g, "");

    // Remove pontuação final capturada por OCR.
    numero = numero.replace(/[.,]+$/, "");

    const valor = parseValorBR(numero);

    if(valor > 0){
      return {
        valor,
        textoEncontrado: match[0]
      };
    }
  }

  return null;
}

async function reconhecerPrintRecebimento(file, onProgress){
  if(!window.Tesseract){
    throw new Error("Biblioteca OCR não carregada.");
  }

  const resultado = await window.Tesseract.recognize(
    file,
    "por",
    {
      logger: info => {
        if(
          info?.status === "recognizing text"
          && typeof info.progress === "number"
        ){
          onProgress?.(
            Math.round(info.progress * 100)
          );
        }
      }
    }
  );

  return resultado?.data?.text || "";
}

function iniciarCalculadora(container){
  if(!container || container.dataset.calcReady === "1"){
    return;
  }

  container.dataset.calcReady = "1";

  const valorInput = container.querySelector("[data-calc-valor]");
  const percentualInput = container.querySelector("[data-calc-percent]");
  const percentualTexto = container.querySelector("[data-calc-percent-text]");
  const enviar = container.querySelector("[data-calc-enviar]");
  const ganho = container.querySelector("[data-calc-ganho]");
  const original = container.querySelector("[data-calc-original]");
  const taxa = container.querySelector("[data-calc-taxa]");
  const copiarCompleto = container.querySelector("[data-calc-copy-full]");
  const limpar = container.querySelector("[data-calc-clear]");
  const status = container.querySelector("[data-calc-status]");
  const presets = container.querySelectorAll("[data-percentual]");

  const printInput = container.querySelector("[data-calc-print]");
  const ocrStatus = container.querySelector("[data-calc-ocr-status]");
  const uploadTitle = container.querySelector("[data-calc-upload-title]");
  const uploadSubtitle = container.querySelector("[data-calc-upload-subtitle]");
  const previewWrap = container.querySelector("[data-calc-preview-wrap]");
  const preview = container.querySelector("[data-calc-preview]");

  let previewUrl = null;


  function percentualSeguro(){
    let valor = Number(percentualInput?.value || 25);

    valor = Math.max(
      MIN_PERCENT,
      Math.min(MAX_PERCENT, valor)
    );

    if(percentualInput){
      percentualInput.value = String(valor);
    }

    return valor;
  }

  function atualizarPreset(percentual){
    presets.forEach(botao => {
      botao.classList.toggle(
        "active",
        Number(botao.dataset.percentual) === percentual
      );
    });
  }

  function calcular(){
    const valor = parseValorBR(valorInput?.value);
    const percentual = percentualSeguro();

    const valorGanho = valor * percentual / 100;
    const valorEnviar = valor - valorGanho;

    if(percentualTexto){
      percentualTexto.textContent = `${percentual}%`;
    }

    if(taxa){
      taxa.textContent = `${percentual}%`;
    }

    if(original){
      original.textContent = formatarBRL(valor);
    }

    if(ganho){
      ganho.textContent = formatarBRL(valorGanho);
    }

    if(enviar){
      enviar.textContent = formatarBRL(valorEnviar);
    }

    atualizarPreset(percentual);

    return {
      valor,
      percentual,
      valorGanho,
      valorEnviar
    };
  }

  valorInput?.addEventListener("input", () => {
    const somenteDigitos = String(valorInput.value || "").replace(/[^\d]/g, "");

    if(somenteDigitos){
      valorInput.value = Number(somenteDigitos).toLocaleString("pt-BR");
    }else{
      valorInput.value = "";
    }

    if(status){
      status.textContent = "";
    }

    calcular();
  });


  printInput?.addEventListener("change", async () => {
    const file = printInput.files?.[0];

    if(!file){
      return;
    }

    if(!file.type.startsWith("image/")){
      if(ocrStatus){
        ocrStatus.textContent = "❌ Selecione uma imagem válida.";
      }
      return;
    }

    if(previewUrl){
      URL.revokeObjectURL(previewUrl);
    }

    previewUrl = URL.createObjectURL(file);

    if(preview && previewWrap){
      preview.src = previewUrl;
      previewWrap.hidden = false;
    }

    if(uploadTitle){
      uploadTitle.textContent = file.name;
    }

    if(uploadSubtitle){
      uploadSubtitle.textContent = "Processando print...";
    }

    if(ocrStatus){
      ocrStatus.textContent = "🔎 Preparando OCR...";
    }

    printInput.disabled = true;

    try{
      const textoOCR = await reconhecerPrintRecebimento(
        file,
        progresso => {
          if(ocrStatus){
            ocrStatus.textContent =
              `🔎 Lendo valor recebido... ${progresso}%`;
          }
        }
      );

      const encontrado = extrairValorRecebidoOCR(textoOCR);

      if(!encontrado){
        if(ocrStatus){
          ocrStatus.textContent =
            "⚠️ Não encontrei “Você recebeu R$...”. Confira se o texto está visível no print ou digite o valor manualmente.";
        }

        if(uploadSubtitle){
          uploadSubtitle.textContent =
            "OCR concluído — valor não identificado";
        }

        return;
      }

      if(valorInput){
        valorInput.value = Math.round(
          encontrado.valor
        ).toLocaleString("pt-BR");
      }

      calcular();

      if(ocrStatus){
        ocrStatus.textContent =
          `✅ Valor identificado: ${formatarBRL(encontrado.valor)}. Agora escolha a porcentagem.`;
      }

      if(uploadSubtitle){
        uploadSubtitle.textContent =
          "Valor preenchido automaticamente";
      }
    }
    catch(erro){
      console.error(
        "Erro no OCR da calculadora:",
        erro
      );

      if(ocrStatus){
        ocrStatus.textContent =
          "❌ Não foi possível ler o print. Você ainda pode informar o valor manualmente.";
      }

      if(uploadSubtitle){
        uploadSubtitle.textContent =
          "Falha na leitura OCR";
      }
    }
    finally{
      printInput.disabled = false;
    }
  });

  percentualInput?.addEventListener("input", () => {
    if(status){
      status.textContent = "";
    }

    calcular();
  });

  presets.forEach(botao => {
    botao.addEventListener("click", () => {
      if(percentualInput){
        percentualInput.value = botao.dataset.percentual;
      }

      if(status){
        status.textContent = "";
      }

      calcular();
    });
  });

  copiarCompleto?.addEventListener("click", async () => {
    const resultado = calcular();

    if(!resultado.valor){
      if(status){
        status.textContent = "⚠️ Informe um valor primeiro.";
      }
      return;
    }

    const texto = [
      "CHINA PRO — CÁLCULO",
      `Valor original: ${formatarBRL(resultado.valor)}`,
      `Porcentagem: ${resultado.percentual}%`,
      `Valor da porcentagem: ${formatarBRL(resultado.valorGanho)}`,
      `Valor a enviar: ${formatarBRL(resultado.valorEnviar)}`
    ].join("\n");

    try{
      await copiarTexto(texto);

      if(status){
        status.textContent = "✅ Cálculo completo copiado.";
      }
    }catch{
      if(status){
        status.textContent =
          "❌ Não foi possível copiar o cálculo.";
      }
    }
  });

  limpar?.addEventListener("click", () => {
    if(valorInput){
      valorInput.value = "";
      valorInput.focus();
    }

    if(percentualInput){
      percentualInput.value = "25";
    }

    if(status){
      status.textContent = "";
    }

    calcular();
  });

  calcular();
}

document.addEventListener("DOMContentLoaded", () => {
  document
    .querySelectorAll("[data-calculadora]")
    .forEach(iniciarCalculadora);
});

window.iniciarCalculadoraChinaPro = iniciarCalculadora;
window.parseValorCalculadoraChinaPro = parseValorBR;
window.extrairValorRecebidoCalculadoraChinaPro = extrairValorRecebidoOCR;
})();