"use strict";

function applySisalActive(source) {
  const text = source.replace(/\r\n/g, "\n");
  const hook = "    // Authenticated state sync uses the same existing webhook secret.";
  const dashboard = "    if (bancoDashboardContext_) {segretarioRiceviUpdate_(update);return rispostaOK();}";
  if (text.split(hook).length !== 2 ||
      text.split(dashboard).length !== 2 ||
      text.indexOf(dashboard) > text.indexOf(hook) ||
      text.includes("bancoRiceviPrelievoSisal_")) {
    throw new Error("Banco baseline differs from the authenticated webhook layout");
  }
  return text.replace(hook,
    "    if (update && Object.prototype.hasOwnProperty.call(update, 'banco_sisal_withdrawal')) {\n" +
    "      return bancoRiceviPrelievoSisal_(update.banco_sisal_withdrawal);\n" +
    "    }\n\n" + hook);
}

module.exports = {applySisalActive};
