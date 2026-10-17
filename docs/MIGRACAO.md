# Perfis e conversões

Referência observada: https://kindpump.github.io/, em 2026-10-14.
Repositório correlacionado: https://github.com/kindpump/kindpump.github.io/tree/67bf49efa2ef1142ad3bd09c51c17f5088a6306d .
Nenhuma licença geral foi demonstrada nessa revisão. A base de redistribuição
dos perfis permanece pendente; números isolados e a coleção não devem ser
tratados automaticamente como se tivessem a mesma proteção ou permissão.

## Valores preservados

São 75 operadores, 150 configurações de arma e 450 valores. Cada linha legada
contém T1,X1,Y1,T2,X2,Y2. O catálogo conserva strings decimais sem arredondar,
inverter sinais ou aplicar multiplicadores aos valores armazenados.

| Campo | Exibição antiga | Valor usado nesta aplicação |
|---|---|---|
| X | X | X |
| Y | −Y | Y |
| Speed primária | T | T, em segundos |
| Speed secundária | 10 × T | T, em segundos |

Exemplos: Ash secundária T=0.04; Jäger primária Y=6; Fuze secundária T=0,
X=0.099, Y=-0.2. Vigil primária T=0.00099 é conservado como dado legado,
mas não é elegível para execução pelo limite mínimo de 0.001 s.
T zero não é convertido automaticamente em outro intervalo.

## Multiplicadores e frações

O motor aplica Xbase × MX e Ybase × MY uniformemente às duas armas.
1 significa 1×. Isso corrige intencionalmente as inconsistências de aplicação
dos fatores entre caminhos da interface antiga. Uma representação histórica
em que 1000 significa 1× deve ser dividida exatamente por 1000.

Os produtos e resíduos usam frações exatas construídas de strings decimais.
O sorteio X ou zero antecede a acumulação. A emissão trunca em direção a zero
e conserva o resíduo até uma transição que exija reinicialização.
Esses cálculos não reescrevem os valores-base.

O modelo de comparação em tools/audit_profiles.py representa o comportamento
legado, não a regra uniforme atual. Não se afirma equivalência com a antiga
perda de frações. Testes verificam os 450 valores, conversões, pausas e seleção.

## Compatibilidade e proveniência

A importação legada usa os valores-base, sem conversão de Y ou Speed.
Veja [Formato legado](FORMATO-LEGADO.md).
A implementação foi reconstruída com observação de comportamento e evidências
do programa de referência. Não é apresentada como clean room rigoroso.
A conclusão sobre eventual reutilização de código e a autorização dos perfis
deve ser registrada no [checklist](PROXIMOS_PASSOS_PUBLICACAO.md).
