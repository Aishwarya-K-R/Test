using System.Text.Json;
using Confluent.Kafka;
using Patient_Management_System.Services;

namespace Patient_Management_System.Kafka
{
    public class AIKafkaConsumer(IConfiguration config, RedisService redis) : BackgroundService
    {
        private readonly IConfiguration _config = config;
        private readonly RedisService _redis = redis;

        protected override Task ExecuteAsync(CancellationToken stoppingToken)
        {
            var consumerConfig = new ConsumerConfig
            {
                BootstrapServers = _config["Kafka:BootstrapServers"],
                GroupId = _config["Kafka:GroupId"],
                AutoOffsetReset = AutoOffsetReset.Earliest
            };

            return Task.Run(async () =>
            {
                using var consumer = new ConsumerBuilder<Ignore, string>(consumerConfig).Build();

                var topics = new[]
                {
                    _config["Kafka:PatientCreatedTopic"],
                    _config["Kafka:PatientUpdatedTopic"],
                    _config["Kafka:PatientDeletedTopic"],
                    _config["Kafka:BillingCreatedTopic"]
                };

                consumer.Subscribe(topics);

                try
                {
                    while (!stoppingToken.IsCancellationRequested)
                    {
                        var result = consumer.Consume(stoppingToken);
                        Console.WriteLine($"AI Consumer received: {result.Message.Value}");

                        var json = JsonDocument.Parse(result.Message.Value);

                        if (!json.RootElement.TryGetProperty("PatientId", out var patientIdProp))
                            continue;

                        var patientId = patientIdProp.GetInt32();

                        if (result.Topic == _config["Kafka:PatientDeletedTopic"])
                        {
                            await _redis.ClearPatientContextAsync(patientId);
                            Console.WriteLine($"Deleted patient {patientId} removed from Redis cache.");
                        }
                        else
                        {
                            await _redis.MarkUpdatedAsync(patientId);
                            Console.WriteLine($"Patient {patientId} marked as updated for RAG.");
                        }
                    }
                }
                catch (OperationCanceledException)
                {
                    consumer.Close();
                }

            }, stoppingToken);
        }
    }
}