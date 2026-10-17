# Checklist final — Recoil-training-V1

Atualização: 2026-10-17. **Somente preparação local; publicação bloqueada.**
Nome público: Recoil-training-V1. Futura Release: Recoil-training-V1 v1.0.0.
Executável e nomes internos: R6-Rebuild. Nenhuma função foi alterada nesta etapa.

## Organização e histórico

- [x] Código em src/, interface em frontend/, perfis em data/, testes em tests/.
- [x] Assets com a logo de correntes, documentação pública, scripts de build,
  dependências, LICENSE, THIRD_PARTY_NOTICES.txt e licenses/ preservados.
- [x] Relatórios internos e utilitários de auditoria separados em arquivo local
  privado. Documentação útil de migração e compatibilidade revisada.
- [x] build/, dist/, publication-private/, caches, logs e configurações pessoais
  excluídos do versionamento. Nenhuma distribuição é arquivo do repositório.
- [x] Histórico público derivado da prévia sem arte antiga, filtrando também
  documentação interna histórica; arquivos atuais aprovados reintegrados.
  Backups completos do histórico e documentos anteriores ficam somente locais.
- [ ] Antes do push, repetir a conferência de todos os objetos, autores, arquivos
  e referências do histórico definitivo. Nunca enviar backups ou pastas privadas.

## Candidato local da Release

Arquivo: Recoil-training-V1-v1.0.0-Windows-x64.zip, na área ignorada
publication-private/release-staging-20261017/.
Tamanho: 13.433.954 bytes. SHA-256:

```text
7214c03352b47817a75cd98c5065d4096fa65f042cd17d003bdc092e24b27f90
```

- [x] 263 arquivos: R6-Rebuild.exe, _internal/, licenses/, avisos e instruções.
- [x] EXE copiado sem recompilação nem alteração da distribuição com correntes.
  SHA-256: daa79b793aff72e4cc1eb53f0bfdff067ce3a8bbe2c2062c488080abe72c5db4.
- [x] Ícone PE conferido contra os sete quadros aprovados (16 a 256 px).
  Ícone de janela presente; aparência no Explorer não foi homologada visualmente.
- [x] 75 perfis e 75 SVG, frontend e recursos comparados às fontes.
- [x] CRC, extração e hashes de todos os arquivos aprovados; metadados externos
  do ZIP sem comentários, campos extras ou caminhos absolutos.
- [x] 282 testes Python + 24 JavaScript aprovados; 33 autoverificações do EXE
  extraído aprovadas com saída descartável. Início em Simulação e pausa ativa.
- [x] Inspeção estática de 692 módulos compilados, inclusive arquivos comprimidos.
  Nenhum nome/caminho local do responsável ou token reconhecido encontrado.
- [ ] Ressalva de metadados: dois DLLs oficiais do ClrLoader contêm caminhos PDB
  do ambiente de build do fornecedor. Não são dados do responsável pelo projeto.
  Créditos/e-mails de autores e metadados de proveniência da arte foram mantidos.
  A busca por padrões não prova ausência absoluta de todo segredo possível.

O ZIP está sinalizado como **aguardando autorização**, não como Release liberada.
JavaScript/CSS e outros recursos necessários à execução permanecem em _internal;
o projeto-fonte de desenvolvimento não foi incluído. Não houve movimento físico.

## Permissões do projeto de referência — preencher antes de publicar

Referência: https://github.com/kindpump/kindpump.github.io , commit
67bf49efa2ef1142ad3bd09c51c17f5088a6306d. Não foi demonstrada licença geral
no material consultado. Visibilidade pública não equivale a permissão irrestrita.
Não se afirma clean room rigoroso: a reconstrução utilizou observações e evidências.

| Evidência necessária | Registro pendente |
|---|---|
| URL do vídeo/publicação/licença | A fornecer pelo responsável |
| Trecho exato da autorização e contexto | A conferir sem presumir alcance |
| Data e autoria | Identificar autor e capacidade de autorizar |
| Versão/commit/material coberto | Delimitar precisamente |
| Escopo | Modificação, redistribuição de fonte e binários, perfis e arte |
| Condições | Atribuição, avisos, restrições, eventual compartilhamento de fonte |
| Perfis | Concluir especificamente sobre os 450 valores e sua coleção |
| Eventual código reutilizado | Identificar trechos/licenças; distinguir reimplementação |

- [ ] Registrar evidência suficiente, preservar cópia privada e adicionar crédito
  público apropriado. Uma permissão para código não cobre automaticamente marcas
  ou materiais de terceiros. Se o alcance for insuficiente, manter bloqueio.
- [ ] Confirmar direitos da logo com correntes; a MIT própria não a relicencia.
- [x] Avisos MIT dos SVGs r6operators 2.0.0 preservados; marcas não transferidas.

## Dependências e composição nativa

- [x] Python 3.13.14, OpenSSL 3.0.21, pywebview 6.2.1, dependências Python,
  PyInstaller 6.22.3 e ferramentas inventariados; textos reunidos em licenses/.
- [x] proxy_tools 0.1.0: cabeçalho BSD e fonte correspondente esclarecem a
  divergência com metadados MIT; conservar o texto BSD identificado.
- [x] WebView2 SDK 1.0.3856.49: cinco DLLs correspondem ao NuGet oficial;
  LICENSE e NOTICE incluídos. WebView2 Runtime e .NET são requisitos externos.
- [x] 78 nativos classificados: EXE, 23 do Python oficial, 11 de wheels e
  43 UCRT/API sets de runtime auxiliar. Inventários brutos ficam privados.
- [ ] UCRT/API sets 10.0.26100.4654: comprovar cadeia de redistribuição autorizada.
  Origem auxiliar libheif não basta; não se afirma origem System32.
- [ ] VC Runtime 14.42.34438.0: arquivos coincidem com CPython oficial, mas é
  necessário comprovar atendimento aos termos Microsoft aplicáveis ao distribuidor.
- [ ] Concluir o vínculo de composição estática das extensões às fontes/avisos
  aplicáveis, em particular CFFI e WebBrowserInterop. Origem por hash é evidência,
  não prova completa de composição. Limites detalhados nos avisos de terceiros.

Não remover DLLs, aceitar termos, instalar SDKs ou alterar a composição funcional
para aparentar resolução. Ver licenses/Microsoft-redistribution-status.txt e
THIRD_PARTY_NOTICES.txt. Faltam documentos, não evidência de infração automática.

## Quando houver permissões suficientes e autorização final

1. Registrar e revisar as permissões; aplicar créditos e eventuais condições.
2. Resolver Microsoft/composição e aprovar os recursos. Se mudar o pacote,
   montar outro candidato, repetir testes, privacidade, extração e SHA-256.
3. Revalidar histórico, Git limpo, ausência de privados e manifesto da Release.
4. Confirmar conta/destino e autenticar ferramenta oficial, com ajuda do usuário
   somente se necessário.
5. Criar repositório público Recoil-training-V1, enviar somente o histórico
   aprovado, criar tag v1.0.0 e Release Recoil-training-V1 v1.0.0.
6. Anexar ZIP aprovado e SHA-256; preencher README com URLs reais e conferir
   logo e download. Configurar social preview se a integração permitir.

Esses passos poderão ser automatizados após a autorização, respeitando bloqueios.
**Nenhum remoto, push, tag, Release ou upload foi feito nesta preparação.**
