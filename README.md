# Recoil-training-V1

<p align="center"><img src="assets/public/emblema-correntes.png" width="360" alt="Número 6 vermelho, mouse com código, correntes e estrelas"></p>

Aplicativo experimental para Windows com perfis independentes e saída de mouse simulada ou real. Projeto independente, sem vínculo ou aprovação da Ubisoft. Não contém detecção de jogo nem contorno de anticheat. Macros podem contrariar regras de jogos; não há garantia contra punições.

**Recoil-training-V1** é o nome do projeto no GitHub. O aplicativo para
Windows se chama **R6-Rebuild.exe**.

## Instalação

### Requisitos

- Windows de 64 bits (x64).
- Microsoft Edge WebView2 Runtime e .NET Framework compatíveis com o aplicativo.
- Python e Node.js **não são necessários** para usar o ZIP pronto.

Os runtimes não são instalados automaticamente. A compatibilidade com todas
as versões do Windows ainda não foi homologada. O EXE não tem assinatura
digital: não desative o antivírus ou outras proteções para executá-lo.

### Download e extração

A [Release v0.1.0](https://github.com/1hnrq/Recoil-training-V1/releases/tag/v0.1.0)
está disponível para quem tem acesso a este repositório privado. A distribuição
pública ainda depende da conclusão das permissões descritas em
[Licenciamento](docs/LICENCIAMENTO.md).

1. Na Release, abra **Assets** e baixe [Recoil-training-V1-v0.1.0-Windows-x64.zip](https://github.com/1hnrq/Recoil-training-V1/releases/download/v0.1.0/Recoil-training-V1-v0.1.0-Windows-x64.zip).
2. Clique com o botão direito no ZIP e escolha **Extrair tudo**. Não execute de dentro do ZIP.
3. Abra a pasta `R6-Rebuild` extraída e dê dois cliques em `R6-Rebuild.exe`.
4. Mantenha `_internal` ao lado do EXE e preserve os avisos/licenças. Para mover o aplicativo, copie a pasta inteira.
5. Não abra versões simultaneamente: atalhos globais podem se sobrepor e as configurações podem ser compartilhadas.

**Não baixe “Source code (zip)” nem “Code → Download ZIP” para instalar:**
esses arquivos contêm o código-fonte, não o aplicativo pronto.

<details>
<summary>Conferir a integridade do download (opcional)</summary>

No PowerShell, dentro da pasta em que salvou o ZIP, execute:

```powershell
Get-FileHash -Algorithm SHA256 .\Recoil-training-V1-v0.1.0-Windows-x64.zip
```

O resultado deve ser:

```text
7214c03352b47817a75cd98c5065d4096fa65f042cd17d003bdc092e24b27f90
```

Esse hash identifica o ZIP da v0.1.0; não comprova segurança ou autorização
de redistribuição. Se diferir, não execute o arquivo antes de esclarecer a diferença.

</details>

## Primeiros passos

O aplicativo inicia em **Simulação**, com **pausa geral ativada**. Comece nesse estado e confira o Diagnóstico. A simulação não emite movimentos físicos nem remove automaticamente pausas.

1. Escolha o operador e a arma desejada.
2. Confira os parâmetros e a pausa individual dessa arma.
3. Para observar os ciclos simulados, retire a pausa geral de forma explícita
   e acompanhe o Diagnóstico. O cursor não deve se mover em Simulação.
4. Use **F12** para voltar ao estado seguro a qualquer momento.

Escolha um dos 75 operadores e a arma primária ou secundária. Cada arma tem configuração independente. Os valores são observações documentadas em [Migração](docs/MIGRACAO.md), não ajustes garantidos para toda versão do jogo.

| Controle | Significado |
|---|---|
| X | Deslocamento horizontal por ciclo, decimal positivo ou negativo. A escolha original aplica X ou zero com probabilidade de 50% cada. |
| Y | Deslocamento vertical por ciclo. Positivo corresponde a movimento para baixo no Windows. |
| Speed | Intervalo em segundos: 0.020 = 20 ms; 0.100 = 100 ms. Menor intervalo solicita maior frequência. |
| Multiplicadores X/Y | Escalas aplicadas sem reescrever os valores-base: 1 mantém o valor, 0.5 aplica metade e 2 aplica o dobro. |
| Pausa individual | Bloqueia a arma correspondente independentemente da pausa geral. |

Use ponto para os valores decimais, como `0.020`. Speed é um **intervalo**:
quanto menor, mais frequentes são os ciclos. Zero indica um intervalo não
configurado, não velocidade máxima. Confira o motivo de bloqueio no Diagnóstico.

O motor acumula frações de forma exata e emite somente a parte inteira. O mínimo aceito é 0.001 s; isso não garante 1.000 ciclos/s. Não há fila para compensar ciclos atrasados.

## Modos, pausas e atalhos

| Comando | Ação |
|---|---|
| P | Alterna pausa geral ao soltar a tecla. |
| 1 / 2 | Seleciona arma primária / secundária. |
| F12 | Emergência: retorna à Simulação com pausa ativada. |
| L + R físicos | Botões esquerdo e direito do mouse pressionados juntos; necessários para emissão Real, além das demais condições. |

Real exige confirmação explícita e começa pausado. Solte ambos os botões antes de retomar. Soltar L ou R impede novas emissões; uma chamada nativa já entregue ao Windows não pode ser cancelada retroativamente. As pausas individuais permanecem independentes.

O listener foi projetado para funcionar sem foco, inclusive minimizado. A compatibilidade em todas as combinações de dispositivos e aplicativos não está garantida. Não há bypass, injeção ou alteração de arquivos do jogo.

## Salvar e transferir configurações

As configurações são salvas em `%LOCALAPPDATA%\R6-Rebuild\settings.json`, com backup `settings.last-valid.json`. Use **Arquivos** para importar/exportar JSON. Exporte antes de grandes alterações ou troca de versão. Importação não restaura Real nem remove a pausa de segurança. Para outro computador, transfira uma exportação e importe no destino.

Para atualizar, exporte suas configurações, encerre o aplicativo
e extraia a nova versão em uma pasta separada. Não misture arquivos `_internal`
de versões diferentes. As configurações ficam fora da pasta do programa e
normalmente continuam disponíveis; mantenha sua exportação como segurança.

## Diagnóstico e solução de problemas

- **Não abre:** extraia o ZIP completo e confira `_internal`, Windows x64 e runtimes. Não baixe DLLs avulsas de sites desconhecidos.
- **Não movimenta em Simulação:** esperado; não existe saída física nesse modo.
- **Holding = SIM, mas bloqueado:** Holding indica L/R reconciliados, não elegibilidade. Confira pausas, arma habilitada e motivo do bloqueio.
- **L/R divergentes:** compare hook, leitura Windows, estado reconciliado e motor, com idades e sequências. Uma amostra positiva isolada não cria um pressionamento.
- **Real retorna à Simulação:** é uma interrupção de segurança. Solte os dois botões e consulte o motivo e o registro da última falha no Diagnóstico. Não desative proteções nem aumente timeouts para ocultar a causa.
- **Download mostra 404:** enquanto o repositório for privado, entre na conta GitHub que possui acesso. Não procure cópias de terceiros como alternativa.
- **Atalhos duplicados:** encerre outras instâncias.
- **Saída bloqueada em outro aplicativo:** permissões Windows/UIPI podem limitar a saída; não há garantia de aceitação por jogos/anticheat.

Para relatar falhas, informe versão, modo, parâmetros e diagnóstico sanitizado. Revise nomes, caminhos e configurações pessoais antes de compartilhar.

## Limitações e licenças

Não há garantia de tempo real rígido, compatibilidade com jogos ou equivalência completa com o programa observado. Miras ilustrativas não são uma sobreposição global na tela.

A MIT da raiz aplica-se somente ao código e documentação próprios, conforme [LICENCIAMENTO](docs/LICENCIAMENTO.md). Recursos, marcas, perfis e dependências não são automaticamente relicenciados.

As permissões dos perfis/recursos e as condições restantes de redistribuição
de dependências ainda estão em revisão. Manter o repositório privado não
substitui essas permissões. O acompanhamento está no
[checklist de publicação](docs/PROXIMOS_PASSOS_PUBLICACAO.md).

Os avisos reunidos estão em [THIRD_PARTY_NOTICES.txt](THIRD_PARTY_NOTICES.txt) e `licenses/`. Leia as pendências antes de redistribuir.

## Código-fonte e desenvolvimento

O código Python fica em `src/r6_rebuild`, a interface em `frontend`, os perfis
em `data` e os testes em `tests`. Para desenvolver, crie uma `.venv` com Python
3.13 e instale `requirements-build.txt` somente após revisar as dependências.
Execute `python -m unittest discover -s tests` e `npm test` (Node necessário
apenas para testes JavaScript). Para os testes de ponte, configure
`R6_TEST_PYTHON` com o caminho do Python dessa `.venv`.

`tools/build_windows.py` cria distribuições separadas e exige a `.venv` local;
consulte `--help` para destinos de build e relatório. Artefatos em `build/`,
`dist/` e `publication-private/` nunca devem ser enviados ao repositório.
O checklist de publicação está em [Próximos passos](docs/PROXIMOS_PASSOS_PUBLICACAO.md).
