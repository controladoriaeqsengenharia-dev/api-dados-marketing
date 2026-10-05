// Crie uma consulta em branco chamada fnInstagram e cole esta função.
// Credencial: API da Web; informe a chave em Configurações da fonte de dados.
(Tabela as text, optional DataInicial as nullable date, optional DataFinal as nullable date) as table =>
let
    GetPage = (Cursor as text, optional Teto as nullable text) as record =>
        Json.Document(Web.Contents("http://187.127.14.158:8001", [
            RelativePath = "api/data/" & Tabela,
            ApiKeyName = "api_key",
            Query = Record.Combine({
                [after_id = Cursor, limit = "5000"],
                if Teto = null then [] else [until_id = Teto],
                if DataInicial = null then [] else [date_from = Date.ToText(DataInicial, "yyyy-MM-dd")],
                if DataFinal = null then [] else [date_to = Date.ToText(DataFinal, "yyyy-MM-dd")]
            }),
            Timeout = #duration(0, 0, 2, 0)
        ])),
    First = GetPage("0"),
    Pages = List.Generate(
        () => [Page = First, Continue = true],
        each [Continue],
        each if [Page][next_after_id] = null then [Page = [Page], Continue = false]
             else [Page = GetPage([Page][next_after_id], First[until_id]), Continue = true],
        each [Page][data]
    ),
    Columns = List.Transform(First[columns], each [column_name]),
    Result = Table.FromRecords(List.Combine(Pages), Columns, MissingField.UseNull),
    Types = List.Transform(First[columns], each {
        [column_name],
        if [data_type] = "bigint" then Int64.Type
        else if [data_type] = "date" then type date
        else if [data_type] = "timestamp with time zone" then type datetimezone
        else if [data_type] = "numeric" then type number
        else type text
    }),
    Typed = Table.TransformColumnTypes(Result, Types, "en-US")
in
    Typed
