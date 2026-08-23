(() => {
"use strict";

const MIN_PERCENT = 20;
const MAX_PERCENT = 40;

function limparNumero(valor){
  const somenteDigitos =
    String(valor || "")
      .replace(/[^\d]/g, "");

  return Number(
    somenteDigitos || 0
  );
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
  const numero =
    limparNumero(valor);

  if(!numero){
    return "";
  }

  return numero.toLocaleString(
    "pt-BR"
  );
}

document.addEventListener(
  "DOMContentLoaded",
  () => {

    const valorInput =
      document.getElementById(
        "calcValor"
      );

    const percentualInput =
      document.getElementById(
        "calcPorcentagem"
      );

    const percentualTexto =
      document.getElementById(
        "calcPorcentagemTexto"
      );

    const enviar =
      document.getElementById(
        "calcEnviar"
      );

    const ganho =
      document.getElementById(
        "calcGanho"
      );

    const original =
      document.getElementById(
        "calcOriginal"
      );

    const taxa =
      document.getElementById(
        "calcTaxa"
      );

    const copiar =
      document.getElementById(
        "calcCopiar"
      );

    const limpar =
      document.getElementById(
        "calcLimpar"
      );

    const status =
      document.getElementById(
        "calcStatus"
      );

    const presets =
      document.querySelectorAll(
        "[data-percentual]"
      );

    function percentualSeguro(){
      let valor =
        Number(
          percentualInput.value
          || 25
        );

      if(valor < MIN_PERCENT){
        valor = MIN_PERCENT;
      }

      if(valor > MAX_PERCENT){
        valor = MAX_PERCENT;
      }

      percentualInput.value =
        String(valor);

      return valor;
    }

    function atualizarPreset(
      percentual
    ){
      presets.forEach(
        botao => {
          botao.classList.toggle(
            "active",
            Number(
              botao.dataset.percentual
            )
            === percentual
          );
        }
      );
    }

    function calcular(){
      const valor =
        limparNumero(
          valorInput.value
        );

      const percentual =
        percentualSeguro();

      const valorGanho =
        valor
        * percentual
        / 100;

      const valorEnviar =
        valor
        - valorGanho;

      percentualTexto.textContent =
        `${percentual}%`;

      taxa.textContent =
        `${percentual}%`;

      original.textContent =
        formatarBRL(
          valor
        );

      ganho.textContent =
        formatarBRL(
          valorGanho
        );

      enviar.textContent =
        formatarBRL(
          valorEnviar
        );

      atualizarPreset(
        percentual
      );

      return {
        valor,
        percentual,
        valorGanho,
        valorEnviar
      };
    }

    valorInput?.addEventListener(
      "input",
      () => {
        const pos =
          valorInput.selectionStart;

        valorInput.value =
          formatarCampo(
            valorInput.value
          );

        try{
          valorInput.setSelectionRange(
            valorInput.value.length,
            valorInput.value.length
          );
        }catch{}

        calcular();
      }
    );

    percentualInput?.addEventListener(
      "input",
      calcular
    );

    presets.forEach(
      botao => {
        botao.addEventListener(
          "click",
          () => {
            percentualInput.value =
              botao.dataset.percentual;

            calcular();
          }
        );
      }
    );

    limpar?.addEventListener(
      "click",
      () => {
        valorInput.value = "";
        percentualInput.value = "25";
        status.textContent = "";
        calcular();
        valorInput.focus();
      }
    );

    copiar?.addEventListener(
      "click",
      async () => {
        const resultado =
          calcular();

        if(
          !resultado.valor
        ){
          status.textContent =
            "⚠️ Informe um valor antes de copiar.";

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
          await navigator.clipboard.writeText(
            texto
          );

          status.textContent =
            "✅ Cálculo copiado.";
        }
        catch{
          status.textContent =
            "❌ Não foi possível copiar automaticamente.";
        }
      }
    );

    calcular();
  }
);
})();