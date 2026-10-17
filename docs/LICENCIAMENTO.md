# Licenças e procedência

A MIT da raiz aplica-se exclusivamente à implementação e documentação próprias,
na medida dos direitos dos autores. Não relicencia perfis, marcas, imagens ou
componentes de terceiros. Esta revisão documental não é parecer jurídico.

| Item | Situação |
|---|---|
| SVGs dos operadores | r6operators 2.0.0, MIT; conservar frontend/assets/operators/LICENSE.txt e créditos |
| Perfis e referência numérica | Origem documentada, mas autorização geral não demonstrada; pendência antes da publicação |
| Logo com correntes | Fornecida pelo responsável; fora da MIT; revisar direitos de terceiros |
| Arte antiga | Excluída do histórico público preparado e do candidato com correntes; backups privados preservados |
| Dependências | Termos próprios e avisos em THIRD_PARTY_NOTICES.txt e licenses/ |

## Dependências auditadas

Foram identificados 78 binários nativos: EXE próprio, 23 provenientes do Python
oficial, 11 de wheels oficiais e 43 UCRT/API sets de runtime auxiliar.
Python 3.13.14, OpenSSL 3.0.21, pywebview 6.2.1 e dependências possuem avisos
reunidos. WebView2 SDK 1.0.3856.49 coincide com o NuGet oficial.
proxy_tools 0.1.0 foi tratado conforme o cabeçalho BSD do código efetivo e a
licença upstream correspondente, não conforme metadados MIT inconsistentes.

UCRT/API sets 10.0.26100.4654 e VC Runtime 14.42.34438.0 ainda exigem comprovar
o atendimento às condições Microsoft. A origem e os hashes não bastam para
autorizar redistribuição. WebView2 Runtime e .NET Framework são pré-requisitos
externos, não instaladores incluídos no pacote.

A proveniência das extensões foi comparada com artefatos oficiais. A composição
estática completa deve continuar distinguida da correspondência de hashes;
os limites sobre _cffi_backend e WebBrowserInterop constam dos avisos.

Consulte [os próximos passos](PROXIMOS_PASSOS_PUBLICACAO.md) para registrar
as permissões faltantes. A presença dos textos de licença e a aprovação técnica
dos testes não constituem liberação para publicação.
