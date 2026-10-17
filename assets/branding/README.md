# Ícone oficial

Fonte fornecida pelo responsável: `source/logomouse.png`, sem alteração dos pixels originais.
SHA256: `0d3a6bc70915273f0dbff5bd9725639a1af277aa12c8dfea1f9d9e838c881e8f`.

`r6-rebuild.ico`: 16, 24, 32, 48, 64, 128 e 256 px, RGBA 32 bits,
quadros PNG comprimidos. O fundo preto da arte foi preservado, sem transparência
artificial, cortes ou remoção de louros/estrelas/mouse/código/número.

Conversão determinística por `tools/convert_brand_icon.py`, usando Pillow 12.3.0
do runtime de ferramentas já disponível, sem instalar dependências.
Cada quadro é reamostrado diretamente do PNG de 1254 px com Lanczos, evitando
reduções em cascata. `preview.png` exibe os sete tamanhos em pixels nativos.
Detalhes do mouse/código e estrelas não podem ter a legibilidade da arte grande
em 16 px; não foram inventadas variantes que alterariam o design solicitado.

A ferramenta recusa sobrescrever os resultados. Para reproduzir, use uma cópia
do projeto sem os arquivos de saída; a fonte é sempre somente leitura.
Pillow não é necessário para executar o aplicativo nem é incluído no pacote.

O PyInstaller incorpora o ICO no EXE e copia somente o ICO para `_internal/assets/branding`.
O backend WinForms do pywebview carrega esse mesmo arquivo como `Form.Icon`.
A janela usa o ícone no título e como ícone de aplicativo na barra de tarefas.
Não são criados/modificados atalhos fixados, caches do Explorer ou ajustes do Windows.

Origem/autorização de uso: imagem enviada pelo usuário para esta aplicação.
Não se atribui uma licença de redistribuição de terceiros que não tenha sido fornecida.

O responsável informa que a arte deriva de uma logo antiga do jogo.
A imagem nova com correntes não resolve a permissão de redistribuir este ícone.
