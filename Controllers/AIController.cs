using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Options;
using Patient_Management_System.Models;
using Patient_Management_System.Services;

namespace Patient_Management_System.Controllers
{
    [ApiController]
    [Route("ai")]
    public class AIController(
        RedisService redis,
        ContextService context,
        LLMService llm,
        IOptions<AI> settings,
        ILogger<AIController> logger
    ) : ControllerBase
    {
        private readonly RedisService _redis = redis;
        private readonly ContextService _context = context;
        private readonly LLMService _llm = llm;
        private readonly AI _settings = settings.Value;
        private readonly ILogger<AIController> _logger = logger;

        [HttpPost("ask")]
        public async Task<IActionResult> Ask([FromBody] string request)
        {
            if (string.IsNullOrWhiteSpace(request))
                return BadRequest("Question is required");

            var updatedIds = await _redis.GetUpdatedPatientsAsync();
            var cachedContext = await _redis.GetAllPatientContextsAsync();

            bool isRedisEmpty = cachedContext.Count == 0;

            Dictionary<int, string> updatedContextDict;

            if (isRedisEmpty)
            {
                _logger.LogInformation("Redis empty - loading full patient context...");
                var allIds = await _context.GetAllPatientIdsAsync();
                updatedContextDict = await _context.GetPatientContextDictAsync(allIds);
            }
            else if (updatedIds.Any())
            {
                _logger.LogInformation($"Partial update for {updatedIds.Count} patients...");
                updatedContextDict = await _context.GetPatientContextDictAsync(updatedIds);
            }
            else
            {
                updatedContextDict = new Dictionary<int, string>();
            }

            foreach (var kv in updatedContextDict)
            {
                await _redis.SetPatientContextAsync(kv.Key, kv.Value);
                cachedContext[kv.Key] = kv.Value;
            }

            await _redis.ClearUpdatedPatientsAsync();

            var finalContext = string.Join("\n", cachedContext.Values);

            if (string.IsNullOrWhiteSpace(finalContext))
            {
                _logger.LogWarning("No data available for AI response");
                return Ok(new { answer = _settings.NoDataMessage });
            }

            var rulesText = string.Join("\n- ", _settings.Rules);

            var prompt = $@"
                {_settings.SystemPrompt}

                STRICT RULES:
                - {rulesText}

                DATA:
                {finalContext}

                QUESTION:
                {request}";

            var answer = await _llm.AskAsync(prompt);
            var readableAnswer = answer.Replace("\\n", Environment.NewLine);

            _logger.LogInformation(
                "AI Question: {Question}\nAI Answer:\n{Answer}",
                request,
                readableAnswer
            );

            return Content(readableAnswer, "text/plain");
        }
    }
}