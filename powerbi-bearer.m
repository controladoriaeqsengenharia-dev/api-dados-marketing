let
    BaseUrl = "http://187.127.14.158:8001",
    TokenAPI = "COLE_O_API_TOKEN_DO_ENV",
    NomeTabela = "instagram_daily_insights",
    TamanhoPagina = 10000,
    BuscarPaginaTentativa = (Inicio as number, Tentativa as number, Teto as nullable text) as record =>
        let
            Resultado = try Json.Document(Web.Contents(BaseUrl, [
                RelativePath = "api/data/" & NomeTabela,
                Query = Record.Combine({
                    [limit = Text.From(TamanhoPagina), offset = Text.From(Inicio)],
                    if Teto = null then [] else [until_id = Teto]
                }),
                Headers = [Authorization = "Bearer " & TokenAPI, Accept = "application/json"],
                IsRetry = Tentativa > 1,
                Timeout = #duration(0, 0, 10, 0)
            ])),
            Resposta =
                if Resultado[HasError] then
                    if Tentativa < 5 then
                        Function.InvokeAfter(
                            () => @BuscarPaginaTentativa(Inicio, Tentativa + 1, Teto),
                            #duration(0, 0, 0, Tentativa * 5)
                        )
                    else error Error.Record("Falha na API", "Página não carregada após 5 tentativas.",
                        [offset = Inicio, erro = Resultado[Error]])
                else Resultado[Value],
            Validada =
                if Resposta is record then
                    if Record.HasFields(Resposta, {"data", "columns", "until_id"}) then
                        if Resposta[data] is list then Resposta
                        else error "O campo data não é uma lista."
                    else error "Resposta sem data, columns ou until_id."
                else error "Resposta inválida da API."
        in Validada,
    BuscarPagina = (Inicio as number, Teto as nullable text) as record =>
        BuscarPaginaTentativa(Inicio, 1, Teto),
    Primeira = BuscarPagina(0, null),
    Colunas = List.Transform(Primeira[columns], each [column_name]),
    Paginas = List.Generate(
        () => [Inicio = 0, Dados = Primeira[data]],
        each List.Count([Dados]) > 0,
        each [Inicio = [Inicio] + TamanhoPagina,
              Dados = BuscarPagina([Inicio] + TamanhoPagina, Primeira[until_id])[data]],
        each [Dados]
    ),
    Registros = List.Combine(Paginas),
    Tabela = Table.FromRecords(Registros, Colunas, MissingField.UseNull),
    Tipos = List.Transform(Primeira[columns], each {
        [column_name],
        if [data_type] = "bigint" then Int64.Type
        else if [data_type] = "date" then type date
        else if [data_type] = "timestamp with time zone" then type datetimezone
        else if [data_type] = "numeric" then type number
        else type text
    }),
    // A API transmite decimais com ponto; en-US evita interpretar 12.34 como 1234.
    TiposDefinidos = Table.TransformColumnTypes(Tabela, Tipos, "en-US")
in
    TiposDefinidos
