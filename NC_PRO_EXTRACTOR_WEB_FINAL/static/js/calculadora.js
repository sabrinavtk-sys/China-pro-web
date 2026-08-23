(() => {
"use strict";

const MIN_PERCENT = 20;
const MAX_PERCENT = 40;

function limparNumero(valor){
  const somenteDigitos = String(valor || "")
    .replace(/[^\d]/g, "");

  return Number(somenteDigitos || 0);
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
  const numero = limparNumero(valor);
  return numero ? numero.toLocaleString("pt-BR") : "";
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
  const copiarNumero = container.querySelector("[data-calc-copy-number]");
  const copiarCompleto = container.querySelector("[data-calc-copy-full]");
  const limpar = container.querySelector("[data-calc-clear]");
  const status = container.querySelector("[data-calc-status]");
  const presets = container.querySelectorAll("[data-percentual]");

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
    const valor = limparNumero(valorInput?.value);
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
    valorInput.value = formatarCampo(valorInput.value);

    try{
      valorInput.setSelectionRange(
        valorInput.value.length,
        valorInput.value.length
      );
    }catch{}

    if(status){
      status.textContent = "";
    }

    calcular();
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

  copiarNumero?.addEventListener("click", async () => {
    const resultado = calcular();

    if(!resultado.valor){
      if(status){
        status.textContent = "⚠️ Informe um valor primeiro.";
      }
      return;
    }

    try{
      await copiarTexto(
        numeroPuro(resultado.valorEnviar)
      );

      if(status){
        status.textContent =
          `✅ Número copiado: ${numeroPuro(resultado.valorEnviar)}`;
      }
    }catch{
      if(status){
        status.textContent =
          "❌ Não foi possível copiar o número.";
      }
    }
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
})();