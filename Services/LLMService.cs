using Microsoft.Extensions.Options;
using Patient_Management_System.Models;
using System.Text.Json;

namespace Patient_Management_System.Services
{
    public class LLMService(HttpClient http, IOptions<AI> options)
    {
        private readonly HttpClient _http = http;
        private readonly AI _settings = options.Value;

        public async Task<string> AskAsync(string prompt)
        {
            if (string.IsNullOrWhiteSpace(_settings.Model) || string.IsNullOrWhiteSpace(_settings.Endpoint))
            {
                return "LLM Error: Model or Endpoint not configured properly.";
            }

            var response = await _http.PostAsJsonAsync(
                _settings.Endpoint,
                new
                {
                    model = _settings.Model,
                    prompt = prompt,
                    stream = false
                });

            if (!response.IsSuccessStatusCode)
            {
                var error = await response.Content.ReadAsStringAsync();
                return $"LLM Error: {error}";
            }

            var json = await response.Content.ReadFromJsonAsync<JsonElement>();

            if (json.TryGetProperty("response", out var result))
            {
                return result.GetString() ?? "";
            }

            return "No response from AI";
        }
    }
}