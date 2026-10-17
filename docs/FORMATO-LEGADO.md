# Importação de configurações legadas

O formato aceito é texto UTF-8: prefixo literal `^^^` seguido de um array JSON
de 75 strings. Cada string contém seis campos separados por vírgula:
`T1,X1,Y1,T2,X2,Y2`. A identidade do operador depende da posição histórica,
registrada em data/legacy_reference.json, não de ordem alfabética.

## Conversões

- São valores-base: não inverter Y nem multiplicar T2 por dez.
- Multiplicadores, pausas e seleção não existem nesse formato; os respectivos
  valores atuais são preservados. A pausa geral fica ativa após importar.
- A exportação atual usa JSON próprio completo, não o formato legado.
- Ash T2=0.04, Jäger Y1=6 e Fuze T2=0/X2=0.099/Y2=-0.2 são preservados.
- Vigil T1=0.00099 é conservado como legado, mas não fica elegível para execução.

## Validação

São exigidas exatamente 75 strings com seis decimais válidos. Limite de arquivo:
1 MiB. Sem preenchimento, coerção de booleanos ou arredondamento. O contrato
aceita até seis casas decimais e módulo até 1000000, sem expoentes. A validação
integral antecede a confirmação e a escrita.

O arquivo não possui assinatura nem versão: uma permutação válida de 75 linhas
não pode ser detectada automaticamente. A compatibilidade se refere ao formato
e à ordem observados em https://kindpump.github.io/ em 2026-10-14, não a todo
arquivo de qualquer versão antiga. Evidências internas não acompanham o pacote.
