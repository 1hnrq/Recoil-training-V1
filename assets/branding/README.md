# Identidade pública — correntes

`source/logomouse.png` é agora uma cópia exata de
`assets/public/emblema-correntes.png`, fornecida pelo responsável.
SHA-256: `a9dda0d20d237d091caeb64129ac6f72ae662a409e29b3c68d2ad5819b26079b`.
O nome técnico da fonte foi mantido para não alterar o conversor existente.

`r6-rebuild.ico` tem quadros PNG RGBA de 16, 24, 32, 48, 64, 128 e 256 px,
reduzidos diretamente da fonte por Lanczos. `preview.png` mostra os tamanhos
nativos. Em tamanhos pequenos, detalhes finos naturalmente perdem legibilidade;
não houve redesenho, remoção de elementos ou alteração de cores.

O PyInstaller usa o ICO como recurso do EXE. O mesmo arquivo em `_internal`
é carregado pelo backend WinForms para janela e barra de tarefas. Não foram
alterados caches do Explorer nem atalhos fixados.

A arte anterior foi preservada em arquivo local ignorado e no histórico,
mas não está incluída como ícone do novo candidato. Sua presença no histórico
continua relevante para os direitos de uma futura publicação desse histórico.
A nova imagem não é automaticamente coberta pela MIT do código.
