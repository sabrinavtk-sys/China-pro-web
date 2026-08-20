(() => {
  "use strict";

  const MIN_WIDTH = 800;
  const MIN_HEIGHT = 450;
  const MIN_BYTES = 50 * 1024;

  const estado = {
    printEnvio: null,
    printRecebimento: null
  };

  function statusBox(){
    let box = document.getElementById("qualidadePrints");
    if(box) return box;

    box = document.createElement("div");
    box.id = "qualidadePrints";
    box.className = "print-quality-box";
    box.innerHTML = `
      <b>📸 Qualidade dos prints</b>
      <p>Envie prints nítidos, completos e sem informações importantes cortadas. O OCR precisa enxergar valores, Nome/ID e data/hora.</p>
      <div id="qualidadePrintsStatus" class="print-quality-status">Aguardando os dois prints.</div>
    `;

    const btn = document.getElementById("btnProcessar");
    const container = btn?.closest(".processar-container");
    if(container){
      container.parentNode.insertBefore(box, container);
    }
    return box;
  }

  function atualizarStatus(){
    statusBox();
    const el = document.getElementById("qualidadePrintsStatus");
    if(!el) return;

    const valores = Object.values(estado);
    const ruins = valores.filter(v => v && !v.ok);
    const prontos = valores.filter(v => v && v.ok);

    if(ruins.length){
      el.className = "print-quality-status bad";
      el.textContent = "⚠️ Um dos prints está com qualidade/resolução baixa. Troque a imagem antes de processar.";
    }else if(prontos.length === 2){
      el.className = "print-quality-status good";
      el.textContent = "✅ Resolução mínima aprovada. Confira visualmente se todos os dados estão visíveis.";
    }else{
      el.className = "print-quality-status";
      el.textContent = "Aguardando os dois prints.";
    }
  }

  function analisarArquivo(input){
    const file = input?.files?.[0];
    if(!file){
      estado[input.id] = null;
      atualizarStatus();
      return;
    }

    if(!file.type.startsWith("image/")){
      estado[input.id] = {ok:false};
      atualizarStatus();
      return;
    }

    const img = new Image();
    const url = URL.createObjectURL(file);

    img.onload = () => {
      const ok =
        img.naturalWidth >= MIN_WIDTH &&
        img.naturalHeight >= MIN_HEIGHT &&
        file.size >= MIN_BYTES;

      estado[input.id] = {
        ok,
        width: img.naturalWidth,
        height: img.naturalHeight,
        bytes: file.size
      };

      URL.revokeObjectURL(url);
      atualizarStatus();
    };

    img.onerror = () => {
      estado[input.id] = {ok:false};
      URL.revokeObjectURL(url);
      atualizarStatus();
    };

    img.src = url;
  }

  document.addEventListener("DOMContentLoaded", () => {
    statusBox();

    ["printEnvio", "printRecebimento"].forEach(id => {
      const input = document.getElementById(id);
      input?.addEventListener("change", () => analisarArquivo(input));
    });

    const btn = document.getElementById("btnProcessar");
    btn?.addEventListener("click", event => {
      const envio = estado.printEnvio;
      const recebimento = estado.printRecebimento;

      if(!envio || !recebimento){
        return; // o fluxo antigo já avisa quando falta arquivo
      }

      if(!envio.ok || !recebimento.ok){
        event.preventDefault();
        event.stopImmediatePropagation();

        alert(
          "Um dos prints está com qualidade muito baixa para o OCR. " +
          "Envie uma captura mais nítida, sem cortes e com as informações visíveis."
        );
      }
    }, true);
  });
})();