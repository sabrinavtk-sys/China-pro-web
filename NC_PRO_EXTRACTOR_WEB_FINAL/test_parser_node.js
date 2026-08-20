
global.window = global;
require(process.argv[2]);

const casos = [
  {
    envio: "Sucesso Você enviou R$621987 para Davi Knecht #145156.",
    recebido: "Informação Você recebeu o item x829316 DINHEIRO SUJO de Davi Knecht [145156]"
  },
  {
    envio: `- =, a —" - FO OS mo a» | E Você enviou R$621987 pera Davi Knecht £ 145156. x`,
    recebido: "Você recebeu o item x829316 DINHEIRO SUJO de Davi Knecht [145156]"
  }
];

for (const c of casos) {
  const r = global.parseOCR(c.envio, c.recebido);
  console.log("RESULT_TEST", JSON.stringify(r));
}
